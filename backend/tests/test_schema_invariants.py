"""Invariants enforced by the database itself, not by application code.

Each of these protects something a router could otherwise break by accident.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError


@pytest.fixture
def seeded_reference(admin_engine):
    """Load the real reference data (document types, fields, mapping)."""
    import os
    import subprocess
    import sys
    from pathlib import Path
    r = subprocess.run(
        [sys.executable, "-m", "scripts.seed_reference"],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True, text=True, env={**os.environ},
    )
    assert r.returncode == 0, r.stdout + r.stderr
    return True


@pytest.fixture
def a_field_value(admin_engine, two_tenants, seeded_reference):
    """One case_field_values row belonging to tenant A, pending review."""
    with admin_engine.begin() as conn:
        field_id = conn.execute(
            text("SELECT id FROM case_fields WHERE field_key = 'insured_name'")
        ).scalar_one()
        row_id = conn.execute(
            text("""INSERT INTO case_field_values
                    (tenant_id, case_id, field_id, extracted_value, value, status)
                    VALUES (:t, :c, :f, 'first answer', 'first answer', 'pending_review')
                    RETURNING id"""),
            {"t": two_tenants["a"]["tenant"], "c": two_tenants["a"]["case"], "f": field_id},
        ).scalar_one()
    return {"id": row_id, "field_id": field_id}


# ── the frozen-value guarantee ───────────────────────────────────────────────


def test_extracted_value_may_change_while_unreviewed(admin_engine, a_field_value):
    """A better source document arriving later must still be able to correct it."""
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE case_field_values SET extracted_value = 'better answer' WHERE id = :i"),
            {"i": a_field_value["id"]},
        )
        got = conn.execute(
            text("SELECT extracted_value FROM case_field_values WHERE id = :i"),
            {"i": a_field_value["id"]},
        ).scalar()
    assert got == "better answer"


@pytest.mark.parametrize("status", ["confirmed", "edited", "rejected"])
def test_extracted_value_is_frozen_once_reviewed(admin_engine, a_field_value, status):
    """Once a lawyer has touched the field, the AI's original is evidence.

    Enforced by trg_freeze_extracted_value so that no future endpoint - however
    careless - can overwrite it.
    """
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE case_field_values SET status = :s, reviewed_at = now() WHERE id = :i"),
            {"s": status, "i": a_field_value["id"]},
        )
    with pytest.raises((IntegrityError, ProgrammingError, DBAPIError), match="frozen"):
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE case_field_values SET extracted_value = 'tampered' WHERE id = :i"),
                {"i": a_field_value["id"]},
            )


def test_lawyer_can_still_edit_the_current_value_after_review(admin_engine, a_field_value):
    """Freezing extracted_value must not freeze the field itself."""
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE case_field_values SET status='confirmed', reviewed_at=now() WHERE id=:i"),
            {"i": a_field_value["id"]},
        )
        conn.execute(
            text("UPDATE case_field_values SET value='corrected', status='edited' WHERE id=:i"),
            {"i": a_field_value["id"]},
        )
        row = conn.execute(
            text("SELECT value, extracted_value FROM case_field_values WHERE id = :i"),
            {"i": a_field_value["id"]},
        ).one()
    assert row.value == "corrected"
    assert row.extracted_value == "first answer", "the AI's original must survive the edit"


# ── cross-tenant references ──────────────────────────────────────────────────


def test_field_value_cannot_point_at_another_tenants_case(
    admin_engine, two_tenants, seeded_reference
):
    """Foreign-key checks bypass RLS, so this needs a composite key, not a policy."""
    with admin_engine.connect() as conn:
        field_id = conn.execute(text("SELECT id FROM case_fields LIMIT 1")).scalar_one()
    with pytest.raises(IntegrityError):
        with admin_engine.begin() as conn:
            conn.execute(
                text("""INSERT INTO case_field_values (tenant_id, case_id, field_id)
                        VALUES (:t, :c, :f)"""),
                {"t": two_tenants["a"]["tenant"], "c": two_tenants["b"]["case"], "f": field_id},
            )


def test_candidate_cannot_point_at_another_tenants_case(
    admin_engine, two_tenants, seeded_reference
):
    with admin_engine.connect() as conn:
        field_id = conn.execute(text("SELECT id FROM case_fields LIMIT 1")).scalar_one()
        doc_type = conn.execute(text("SELECT id FROM document_types LIMIT 1")).scalar_one()
    with admin_engine.begin() as conn:
        doc_id = conn.execute(
            text("""INSERT INTO documents
                    (tenant_id, case_id, document_type_id, file_name, storage_path,
                     file_format, text_extractable)
                    VALUES (:t, :c, :dt, 'x.pdf', 'k', 'pdf', true) RETURNING id"""),
            {"t": two_tenants["a"]["tenant"], "c": two_tenants["a"]["case"], "dt": doc_type},
        ).scalar_one()
    with pytest.raises(IntegrityError):
        with admin_engine.begin() as conn:
            conn.execute(
                text("""INSERT INTO field_candidates
                        (tenant_id, case_id, document_id, field_id, extraction_run_id, priority)
                        VALUES (:t, :c, :d, :f, :r, 10)"""),
                {"t": two_tenants["a"]["tenant"], "c": two_tenants["b"]["case"],
                 "d": doc_id, "f": field_id, "r": uuid.uuid4()},
            )


# ── reference data sanity ────────────────────────────────────────────────────


def test_every_required_field_has_at_least_one_source(admin_engine, seeded_reference):
    """A required field nothing can produce would block every case forever."""
    with admin_engine.connect() as conn:
        orphans = [
            r[0] for r in conn.execute(text("""
                SELECT cf.field_key FROM case_fields cf
                WHERE cf.is_required
                  AND NOT EXISTS (SELECT 1 FROM document_type_fields dtf
                                  WHERE dtf.field_id = cf.id)
                ORDER BY cf.field_key"""))
        ]
    assert orphans == [], f"required fields with no source document: {orphans}"


def test_mappings_only_reference_extractable_document_types(admin_engine, seeded_reference):
    """Mapping a field to a photo-only type means it would never be looked for."""
    with admin_engine.connect() as conn:
        bad = [
            r[0] for r in conn.execute(text("""
                SELECT DISTINCT dt.type_key
                FROM document_type_fields dtf JOIN document_types dt ON dt.id = dtf.document_type_id
                WHERE NOT dt.is_extractable ORDER BY 1"""))
        ]
    assert bad == [], f"fields mapped to non-extractable types: {bad}"


def test_referral_email_outranks_every_other_source(admin_engine, seeded_reference):
    """It is a fixed template parsed by regex - nothing should ever beat it."""
    with admin_engine.connect() as conn:
        rows = list(conn.execute(text("""
            SELECT cf.field_key, MIN(dtf.priority) FILTER (WHERE dt.type_key = 'referral_email'),
                   MIN(dtf.priority) FILTER (WHERE dt.type_key <> 'referral_email')
            FROM document_type_fields dtf
            JOIN document_types dt ON dt.id = dtf.document_type_id
            JOIN case_fields cf ON cf.id = dtf.field_id
            GROUP BY cf.field_key HAVING COUNT(*) FILTER (WHERE dt.type_key='referral_email') > 0""")))
    assert rows, "no referral_email mappings seeded"
    for field_key, email_prio, other_prio in rows:
        if other_prio is not None:
            assert email_prio < other_prio, (
                f"{field_key}: email priority {email_prio} does not beat {other_prio}"
            )
