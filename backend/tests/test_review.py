"""The review API.

The screen a lawyer actually uses: read every field with its provenance, decide
on each one, and find out what still blocks submission. Extraction is not run
here - the rows it would have written are inserted directly, so these tests
exercise the review rules rather than the model.
"""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from tests.conftest import auth_header, make_case, make_tenant, make_user

BACKEND = Path(__file__).resolve().parent.parent

DEFENCE = "הגנה"
CLAIM = "תביעה"


@pytest.fixture
def seeded(admin_engine):
    r = subprocess.run(
        [sys.executable, "-m", "scripts.seed_reference"],
        cwd=BACKEND, capture_output=True, text=True, env={**os.environ},
    )
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.fixture
def firm(admin_engine, seeded):
    with admin_engine.begin() as conn:
        tenant = make_tenant(conn, "Firm A")
        owner = make_user(conn, tenant, "owner@a.test", role="owner")
        make_user(conn, tenant, "clerk@a.test", role="staff")
        case = make_case(conn, tenant, "2026-0001", owner)
        other_tenant = make_tenant(conn, "Firm B")
        other_owner = make_user(conn, other_tenant, "owner@b.test", role="owner")
        other_case = make_case(conn, other_tenant, "2026-0001", other_owner)
    return {
        "tenant": tenant, "user": owner, "case": case,
        "other_tenant": other_tenant, "other_case": other_case,
    }


@pytest.fixture
def headers(client, firm):
    return auth_header(client, "owner@a.test")


def field_id(conn, key: str) -> uuid.UUID:
    return conn.execute(
        text("SELECT id FROM case_fields WHERE field_key = :k"), {"k": key}
    ).scalar_one()


def set_value(conn, firm, key, value, **kw):
    """Insert the row the resolver would have written."""
    params = {
        "t": firm["tenant"], "c": firm["case"], "f": field_id(conn, key),
        "ev": kw.get("extracted_value", value), "v": value,
        "conf": kw.get("confidence", 0.95), "st": kw.get("status", "pending_review"),
        "hc": kw.get("has_conflict", False), "cc": kw.get("conflict_count", 0),
        "doc": kw.get("document_id"), "pg": kw.get("page"),
        "snip": kw.get("snippet"), "rc": kw.get("resolved_candidate_id"),
    }
    return conn.execute(
        text("""
            INSERT INTO case_field_values
                (tenant_id, case_id, field_id, extracted_value, value, confidence_score,
                 status, has_conflict, conflict_count, source_document_id, source_page,
                 source_snippet, resolved_candidate_id)
            VALUES (:t, :c, :f, :ev, :v, :conf, :st, :hc, :cc, :doc, :pg, :snip, :rc)
            RETURNING id
        """),
        params,
    ).scalar_one()


def make_document(conn, firm, file_name="pleading.pdf", type_key=None):
    type_id = None
    if type_key:
        type_id = conn.execute(
            text("SELECT id FROM document_types WHERE type_key = :k"), {"k": type_key}
        ).scalar_one()
    return conn.execute(
        text("""
            INSERT INTO documents
                (tenant_id, case_id, file_name, storage_path, file_format,
                 text_extractable, processing_status, document_type_id)
            VALUES (:t, :c, :n, :p, 'pdf', true, 'extracted', :dt)
            RETURNING id
        """),
        {"t": firm["tenant"], "c": firm["case"], "n": file_name,
         "p": f"{firm['tenant']}/{firm['case']}/{uuid.uuid4()}.pdf", "dt": type_id},
    ).scalar_one()


def make_candidate(conn, firm, document_id, key, value, **kw):
    return conn.execute(
        text("""
            INSERT INTO field_candidates
                (tenant_id, case_id, document_id, field_id, extraction_run_id, value,
                 confidence, priority, source_page, source_snippet, snippet_verified)
            VALUES (:t, :c, :d, :f, :run, :v, :conf, :prio, :pg, :snip, :ver)
            RETURNING id
        """),
        {"t": firm["tenant"], "c": firm["case"], "d": document_id,
         "f": field_id(conn, key), "run": uuid.uuid4(), "v": value,
         "conf": kw.get("confidence", 0.9), "prio": kw.get("priority", 10),
         "pg": kw.get("page", 1), "snip": kw.get("snippet"),
         "ver": kw.get("snippet_verified")},
    ).scalar_one()


def fields_by_key(client, headers, case_id) -> dict:
    resp = client.get(f"/cases/{case_id}/fields", headers=headers)
    assert resp.status_code == 200, resp.text
    return {f["field_key"]: f for f in resp.json()["fields"]}


# ── the screen ───────────────────────────────────────────────────────────────


def test_every_field_appears_even_with_nothing_extracted(client, headers, firm):
    """An absent field would make the checklist look complete when it is not."""
    body = client.get(f"/cases/{firm['case']}/fields", headers=headers).json()
    assert len(body["fields"]) >= 45
    assert all(f["value"] is None for f in body["fields"])
    assert all(f["status"] == "pending_review" for f in body["fields"])
    # Required fields with no value are the ones the lawyer must be sent to.
    missing = [f for f in body["fields"] if "missing_required" in f["attention_reasons"]]
    assert {f["field_key"] for f in missing} >= {"insured_name", "accident_date"}


def test_source_and_attention_reasons(client, headers, firm, admin_engine):
    with admin_engine.begin() as conn:
        doc = make_document(conn, firm, "pleading.pdf")
        cand = make_candidate(conn, firm, doc, "court_name", "שלום תל אביב",
                              snippet_verified=False)
        set_value(conn, firm, "court_name", "שלום תל אביב", confidence=0.6,
                  has_conflict=True, conflict_count=2, document_id=doc, page=2,
                  snippet="בית משפט השלום בתל אביב", resolved_candidate_id=cand)

    f = fields_by_key(client, headers, firm["case"])["court_name"]
    assert f["source"]["file_name"] == "pleading.pdf"
    assert f["source"]["page"] == 2
    assert f["source"]["snippet"].startswith("בית משפט")
    assert set(f["attention_reasons"]) == {"conflict", "low_confidence", "unverified_snippet"}


def test_unverifiable_snippet_is_not_an_unverified_one(client, headers, firm, admin_engine):
    """NULL means the page had no text layer to check against.

    Most documents here are scans, so treating NULL as a failure would light up
    nearly every field and the flag would stop carrying information.
    """
    with admin_engine.begin() as conn:
        doc = make_document(conn, firm)
        cand = make_candidate(conn, firm, doc, "insured_name", "אפי ושות בע\"מ",
                              snippet_verified=None)
        set_value(conn, firm, "insured_name", "אפי ושות בע\"מ",
                  document_id=doc, resolved_candidate_id=cand)

    f = fields_by_key(client, headers, firm["case"])["insured_name"]
    assert f["attention_reasons"] == []


def test_candidates_list_marks_the_resolved_one(client, headers, firm, admin_engine):
    with admin_engine.begin() as conn:
        registry = make_document(conn, firm, "registry.pdf")
        licence = make_document(conn, firm, "licence.pdf")
        winner = make_candidate(conn, firm, registry, "third_party_owner_name",
                                "דוד כהן", priority=5)
        make_candidate(conn, firm, licence, "third_party_owner_name",
                       "דוד כהן-לוי", priority=20)
        set_value(conn, firm, "third_party_owner_name", "דוד כהן",
                  has_conflict=True, conflict_count=2, resolved_candidate_id=winner)
        fid = field_id(conn, "third_party_owner_name")

    rows = client.get(f"/cases/{firm['case']}/fields/{fid}/candidates", headers=headers).json()
    assert [r["file_name"] for r in rows] == ["registry.pdf", "licence.pdf"]
    assert rows[0]["is_resolved"] is True
    assert rows[1]["is_resolved"] is False


# ── decisions ────────────────────────────────────────────────────────────────


def get_field(client, headers, case_id, key):
    return fields_by_key(client, headers, case_id)[key]


def test_confirm_marks_reviewed_and_freezes_the_extracted_value(
    client, headers, firm, admin_engine
):
    with admin_engine.begin() as conn:
        set_value(conn, firm, "insured_name", "אפי ושות בע\"מ")
    before = get_field(client, headers, firm["case"], "insured_name")

    resp = client.post(
        f"/cases/{firm['case']}/fields/{before['field_id']}/confirm",
        json={"expected_updated_at": before["updated_at"]}, headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "confirmed"
    assert resp.json()["reviewed_at"] is not None

    # The trigger, not the router, is what makes this permanent.
    with admin_engine.begin() as conn:
        with pytest.raises(Exception) as exc:
            conn.execute(
                text("UPDATE case_field_values SET extracted_value = 'x' "
                     "WHERE case_id = :c AND field_id = :f"),
                {"c": firm["case"], "f": before["field_id"]},
            )
        assert "frozen" in str(exc.value)


def test_confirm_refuses_an_empty_value(client, headers, firm, admin_engine):
    with admin_engine.begin() as conn:
        set_value(conn, firm, "insured_address", None, extracted_value=None)
    f = get_field(client, headers, firm["case"], "insured_address")
    resp = client.post(
        f"/cases/{firm['case']}/fields/{f['field_id']}/confirm",
        json={"expected_updated_at": f["updated_at"]}, headers=headers,
    )
    assert resp.status_code == 422
    assert "edit or reject" in resp.json()["detail"]


def test_edit_creates_the_row_for_a_field_nothing_extracted(client, headers, firm):
    """The claim amount in a subrogation case is manual entry by design."""
    f = get_field(client, headers, firm["case"], "claim_amount")
    assert f["updated_at"] is None

    resp = client.patch(
        f"/cases/{firm['case']}/fields/{f['field_id']}",
        json={"value": "12279"}, headers=headers,
    )
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["value"] == "12279"
    assert out["status"] == "edited"
    # NULL is the honest record: the model never claimed anything here.
    assert out["extracted_value"] is None


def test_edit_never_touches_the_extracted_value(client, headers, firm, admin_engine):
    with admin_engine.begin() as conn:
        set_value(conn, firm, "third_party_plate_number", "56414501")
    f = get_field(client, headers, firm["case"], "third_party_plate_number")

    resp = client.patch(
        f"/cases/{firm['case']}/fields/{f['field_id']}",
        json={"value": "1234567", "expected_updated_at": f["updated_at"]}, headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["value"] == "1234567"
    # What the machine claimed survives as evidence of what the human overrode.
    assert resp.json()["extracted_value"] == "56414501"


def test_reject_clears_the_value_but_keeps_the_claim(client, headers, firm, admin_engine):
    with admin_engine.begin() as conn:
        set_value(conn, firm, "our_driver_name", "מישהו אחר")
    f = get_field(client, headers, firm["case"], "our_driver_name")

    resp = client.post(
        f"/cases/{firm['case']}/fields/{f['field_id']}/reject",
        json={"expected_updated_at": f["updated_at"]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["value"] is None
    assert resp.json()["extracted_value"] == "מישהו אחר"
    assert resp.json()["status"] == "rejected"


def test_select_candidate_takes_the_other_document_s_provenance(
    client, headers, firm, admin_engine
):
    with admin_engine.begin() as conn:
        registry = make_document(conn, firm, "registry.pdf")
        licence = make_document(conn, firm, "licence.pdf")
        winner = make_candidate(conn, firm, registry, "third_party_owner_name",
                                "דוד כהן", priority=5, page=1)
        rival = make_candidate(conn, firm, licence, "third_party_owner_name",
                               "דוד כהן-לוי", priority=20, page=3, snippet="כהן-לוי")
        set_value(conn, firm, "third_party_owner_name", "דוד כהן", has_conflict=True,
                  conflict_count=2, document_id=registry, page=1,
                  resolved_candidate_id=winner)
    f = get_field(client, headers, firm["case"], "third_party_owner_name")

    resp = client.post(
        f"/cases/{firm['case']}/fields/{f['field_id']}/select-candidate",
        json={"candidate_id": str(rival), "expected_updated_at": f["updated_at"]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["value"] == "דוד כהן-לוי"
    assert out["status"] == "confirmed"
    assert out["source"]["file_name"] == "licence.pdf"
    assert out["source"]["page"] == 3
    # Picking a side is acknowledging the disagreement.
    assert out["conflict_ack_at"] is not None


def test_a_candidate_from_another_case_is_refused(client, headers, firm, admin_engine):
    with admin_engine.begin() as conn:
        other = {"tenant": firm["other_tenant"], "case": firm["other_case"]}
        doc = make_document(conn, other, "theirs.pdf")
        stranger = make_candidate(conn, other, doc, "insured_name", "לא שלנו")
        set_value(conn, firm, "insured_name", "שלנו")
        fid = field_id(conn, "insured_name")
    f = get_field(client, headers, firm["case"], "insured_name")

    resp = client.post(
        f"/cases/{firm['case']}/fields/{fid}/select-candidate",
        json={"candidate_id": str(stranger), "expected_updated_at": f["updated_at"]},
        headers=headers,
    )
    assert resp.status_code == 422


# ── optimistic locking ───────────────────────────────────────────────────────


def test_a_stale_token_is_refused(client, headers, firm, admin_engine):
    with admin_engine.begin() as conn:
        set_value(conn, firm, "insured_name", "א")
    stale = get_field(client, headers, firm["case"], "insured_name")

    first = client.patch(
        f"/cases/{firm['case']}/fields/{stale['field_id']}",
        json={"value": "ב", "expected_updated_at": stale["updated_at"]}, headers=headers,
    )
    assert first.status_code == 200
    # The second lawyer is still holding the version they loaded.
    second = client.patch(
        f"/cases/{firm['case']}/fields/{stale['field_id']}",
        json={"value": "ג", "expected_updated_at": stale["updated_at"]}, headers=headers,
    )
    assert second.status_code == 409
    assert get_field(client, headers, firm["case"], "insured_name")["value"] == "ב"


def test_omitting_the_token_is_not_a_way_around_the_lock(client, headers, firm, admin_engine):
    with admin_engine.begin() as conn:
        set_value(conn, firm, "insured_name", "א")
    f = get_field(client, headers, firm["case"], "insured_name")

    resp = client.patch(
        f"/cases/{firm['case']}/fields/{f['field_id']}", json={"value": "ב"}, headers=headers
    )
    assert resp.status_code == 409


def test_the_trigger_moves_the_token_on_every_update(client, headers, firm, admin_engine):
    """A lock that depends on a router remembering to set updated_at is not a lock."""
    with admin_engine.begin() as conn:
        set_value(conn, firm, "insured_name", "א")
    before = get_field(client, headers, firm["case"], "insured_name")

    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE case_field_values SET value = 'ב' WHERE case_id = :c AND field_id = :f"),
            {"c": firm["case"], "f": before["field_id"]},
        )
    after = get_field(client, headers, firm["case"], "insured_name")
    assert after["updated_at"] != before["updated_at"]


# ── bulk confirm ─────────────────────────────────────────────────────────────


def test_bulk_confirm_never_skips_silently(client, headers, firm, admin_engine):
    with admin_engine.begin() as conn:
        set_value(conn, firm, "insured_name", "אפי ושות", confidence=0.95)
        set_value(conn, firm, "insured_id", "056414501", confidence=0.4)
        set_value(conn, firm, "accident_date", "2026-05-01", confidence=0.99,
                  has_conflict=True, conflict_count=2)
        # always_needs_review: it feeds the filing deadline.
        set_value(conn, firm, "claim_amount", "12279", confidence=0.99)
        set_value(conn, firm, "insured_address", None, extracted_value=None)
        set_value(conn, firm, "our_driver_name", "נהג", confidence=0.99,
                  status="confirmed")

    resp = client.post(f"/cases/{firm['case']}/fields/bulk-confirm", json={}, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    by_key = {s["field_key"]: s["reason"] for s in body["skipped"]}
    assert by_key["insured_id"] == "low_confidence"
    assert by_key["accident_date"] == "conflict"
    assert by_key["claim_amount"] == "always_needs_review"
    assert by_key["insured_address"] == "no_value"
    assert by_key["our_driver_name"] == "already_reviewed"

    after = fields_by_key(client, headers, firm["case"])
    assert after["insured_name"]["status"] == "confirmed"
    assert after["claim_amount"]["status"] == "pending_review"


def test_bulk_confirm_accepts_a_caller_s_threshold(client, headers, firm, admin_engine):
    with admin_engine.begin() as conn:
        set_value(conn, firm, "insured_id", "056414501", confidence=0.6)

    resp = client.post(
        f"/cases/{firm['case']}/fields/bulk-confirm",
        json={"min_confidence": 0.5}, headers=headers,
    )
    assert resp.json()["min_confidence"] == 0.5
    assert fields_by_key(client, headers, firm["case"])["insured_id"]["status"] == "confirmed"


# ── readiness ────────────────────────────────────────────────────────────────


def decide_every_required_field(client, headers, case_id):
    """Clear the board, so that only the rule under test can still block.

    A field that already carries a value is confirmed rather than overwritten -
    otherwise this helper would stamp 'x' over case_type and quietly change the
    very rule the readiness tests are asserting on.
    """
    for f in fields_by_key(client, headers, case_id).values():
        if not f["required_for_this_case"]:
            continue
        if f["value"]:
            resp = client.post(
                f"/cases/{case_id}/fields/{f['field_id']}/confirm",
                json={"expected_updated_at": f["updated_at"]}, headers=headers,
            )
        else:
            resp = client.patch(
                f"/cases/{case_id}/fields/{f['field_id']}",
                json={"value": "x", "expected_updated_at": f["updated_at"]}, headers=headers,
            )
        assert resp.status_code == 200, resp.text


def test_a_claim_case_is_not_missing_its_court_fields(client, headers, firm, admin_engine):
    """The suit has not been filed yet, so empty court fields are the right answer."""
    with admin_engine.begin() as conn:
        set_value(conn, firm, "case_type", CLAIM)
    decide_every_required_field(client, headers, firm["case"])

    body = client.get(f"/cases/{firm['case']}/readiness", headers=headers).json()
    blocked = {b["field_key"] for b in body["blockers"]}
    assert "court_name" not in blocked
    assert "court_case_number" not in blocked
    assert body["is_ready"] is True


def test_a_defence_case_requires_the_court_fields(client, headers, firm, admin_engine):
    with admin_engine.begin() as conn:
        set_value(conn, firm, "case_type", DEFENCE)
    decide_every_required_field(client, headers, firm["case"])

    body = client.get(f"/cases/{firm['case']}/readiness", headers=headers).json()
    assert body["case_type"] == DEFENCE
    # confirm_all_required filled them, so readiness should now be clear...
    assert body["is_ready"] is True
    # ...but they were genuinely part of the required set.
    fields = fields_by_key(client, headers, firm["case"])
    assert fields["court_case_number"]["required_for_this_case"] is True
    assert fields["claim_amount"]["required_for_this_case"] is True


def test_court_fields_block_a_defence_case_while_empty(client, headers, firm, admin_engine):
    with admin_engine.begin() as conn:
        set_value(conn, firm, "case_type", DEFENCE)

    body = client.get(f"/cases/{firm['case']}/readiness", headers=headers).json()
    blocked = {b["field_key"] for b in body["blockers"]}
    assert {"court_name", "court_case_number", "claim_amount"} <= blocked
    assert body["is_ready"] is False


def test_an_extracted_but_unconfirmed_field_still_blocks(client, headers, firm, admin_engine):
    """A machine value nobody looked at is not a decision."""
    with admin_engine.begin() as conn:
        set_value(conn, firm, "case_type", CLAIM)
        set_value(conn, firm, "insured_name", "אפי ושות")

    body = client.get(f"/cases/{firm['case']}/readiness", headers=headers).json()
    reasons = {b["field_key"]: b["reason"] for b in body["blockers"]}
    assert reasons["insured_name"] == "unconfirmed"


def test_rejected_means_wrong_not_inapplicable(client, headers, firm, admin_engine):
    with admin_engine.begin() as conn:
        set_value(conn, firm, "case_type", CLAIM)
        set_value(conn, firm, "insured_name", "שם שגוי")
    f = get_field(client, headers, firm["case"], "insured_name")
    client.post(
        f"/cases/{firm['case']}/fields/{f['field_id']}/reject",
        json={"expected_updated_at": f["updated_at"]}, headers=headers,
    )

    body = client.get(f"/cases/{firm['case']}/readiness", headers=headers).json()
    reasons = {b["field_key"]: b["reason"] for b in body["blockers"]}
    assert reasons["insured_name"] == "rejected"


def test_a_missing_referral_email_is_said_out_loud(client, headers, firm):
    body = client.get(f"/cases/{firm['case']}/readiness", headers=headers).json()
    assert "referral_email_missing" in {w["code"] for w in body["warnings"]}


def test_a_present_referral_email_raises_no_warning(client, headers, firm, admin_engine):
    with admin_engine.begin() as conn:
        make_document(conn, firm, "referral.eml", type_key="referral_email")
    body = client.get(f"/cases/{firm['case']}/readiness", headers=headers).json()
    assert "referral_email_missing" not in {w["code"] for w in body["warnings"]}


def test_an_uncomputed_defence_deadline_warns_but_does_not_block(
    client, headers, firm, admin_engine
):
    with admin_engine.begin() as conn:
        set_value(conn, firm, "case_type", DEFENCE)
    body = client.get(f"/cases/{firm['case']}/readiness", headers=headers).json()
    assert "deadline_not_computed" in {w["code"] for w in body["warnings"]}
    assert "defence_deadline" not in {b["field_key"] for b in body["blockers"]}


def test_an_unknown_case_type_warns_and_requires_the_smaller_set(
    client, headers, firm
):
    body = client.get(f"/cases/{firm['case']}/readiness", headers=headers).json()
    assert body["case_type"] is None
    assert "case_type_unknown" in {w["code"] for w in body["warnings"]}
    assert "court_name" not in {b["field_key"] for b in body["blockers"]}


# ── case status, roles, isolation ────────────────────────────────────────────


def test_reading_the_screen_does_not_freeze_the_case(client, headers, firm, admin_engine):
    """'in_review' is terminal for extraction; a glance must not trigger it."""
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE cases SET status = 'ready_for_review' WHERE id = :c"),
            {"c": firm["case"]},
        )
    client.get(f"/cases/{firm['case']}/fields", headers=headers)
    client.get(f"/cases/{firm['case']}/readiness", headers=headers)
    assert client.get(f"/cases/{firm['case']}", headers=headers).json()["status"] == "ready_for_review"


def test_the_first_decision_moves_the_case_into_review(client, headers, firm, admin_engine):
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE cases SET status = 'ready_for_review' WHERE id = :c"),
            {"c": firm["case"]},
        )
        set_value(conn, firm, "insured_name", "אפי ושות")
    f = get_field(client, headers, firm["case"], "insured_name")
    client.post(
        f"/cases/{firm['case']}/fields/{f['field_id']}/confirm",
        json={"expected_updated_at": f["updated_at"]}, headers=headers,
    )
    assert client.get(f"/cases/{firm['case']}", headers=headers).json()["status"] == "in_review"


def test_a_submitted_case_accepts_no_more_decisions(client, headers, firm, admin_engine):
    with admin_engine.begin() as conn:
        set_value(conn, firm, "insured_name", "אפי ושות")
        conn.execute(
            text("UPDATE cases SET status = 'submitted' WHERE id = :c"), {"c": firm["case"]}
        )
    f = get_field(client, headers, firm["case"], "insured_name")
    resp = client.post(
        f"/cases/{firm['case']}/fields/{f['field_id']}/confirm",
        json={"expected_updated_at": f["updated_at"]}, headers=headers,
    )
    assert resp.status_code == 409


def test_staff_may_read_the_screen_but_not_decide(client, firm, admin_engine):
    """Uploading is clerical. Deciding a value is correct is legal judgement."""
    with admin_engine.begin() as conn:
        set_value(conn, firm, "insured_name", "אפי ושות")
    staff = auth_header(client, "clerk@a.test")

    assert client.get(f"/cases/{firm['case']}/fields", headers=staff).status_code == 200
    f = get_field(client, staff, firm["case"], "insured_name")
    resp = client.post(
        f"/cases/{firm['case']}/fields/{f['field_id']}/confirm",
        json={"expected_updated_at": f["updated_at"]}, headers=staff,
    )
    assert resp.status_code == 403


def test_another_firm_s_case_is_not_found(client, headers, firm):
    assert client.get(f"/cases/{firm['other_case']}/fields", headers=headers).status_code == 404
    assert client.get(f"/cases/{firm['other_case']}/readiness", headers=headers).status_code == 404


def test_every_decision_writes_an_audit_row(client, headers, firm, admin_engine):
    with admin_engine.begin() as conn:
        set_value(conn, firm, "insured_name", "אפי ושות")
    f = get_field(client, headers, firm["case"], "insured_name")
    client.post(
        f"/cases/{firm['case']}/fields/{f['field_id']}/confirm",
        json={"expected_updated_at": f["updated_at"]}, headers=headers,
    )
    with admin_engine.begin() as conn:
        actions = [
            r[0] for r in conn.execute(
                text("SELECT action FROM audit_log WHERE case_id = :c"), {"c": firm["case"]}
            )
        ]
    assert "field.confirmed" in actions


# ── the case type is a closed choice ─────────────────────────────────────────


def test_a_near_miss_case_type_is_refused_not_absorbed(client, headers, firm, admin_engine):
    """"להגשת הגנה" must not quietly become "not a defence case".

    Every court-field rule compares this value exactly. Accepting a near miss
    would stop requiring the court fields on a defence case and let it look
    ready to submit with no court case number - silently, and in the direction
    that loses a filing.
    """
    with admin_engine.begin() as conn:
        set_value(conn, firm, "case_type", DEFENCE)
    f = get_field(client, headers, firm["case"], "case_type")

    resp = client.patch(
        f"/cases/{firm['case']}/fields/{f['field_id']}",
        json={"value": "להגשת הגנה", "expected_updated_at": f["updated_at"]},
        headers=headers,
    )
    assert resp.status_code == 422
    assert DEFENCE in resp.json()["detail"] and CLAIM in resp.json()["detail"]
    # ...and the defence rules are still in force.
    assert fields_by_key(client, headers, firm["case"])["court_name"]["required_for_this_case"]


def test_switching_between_the_two_types_is_allowed(client, headers, firm, admin_engine):
    with admin_engine.begin() as conn:
        set_value(conn, firm, "case_type", DEFENCE)
    f = get_field(client, headers, firm["case"], "case_type")

    resp = client.patch(
        f"/cases/{firm['case']}/fields/{f['field_id']}",
        json={"value": CLAIM, "expected_updated_at": f["updated_at"]}, headers=headers,
    )
    assert resp.status_code == 200, resp.text
    # The court fields stop being required the moment the type says so.
    after = fields_by_key(client, headers, firm["case"])
    assert after["court_name"]["required_for_this_case"] is False


def test_an_unrecognised_case_type_already_in_the_data_blocks(
    client, headers, firm, admin_engine
):
    """The API refuses to write one, but data written before it could not.

    Such a value must block rather than read as 'unknown' - unknown quietly
    drops the court fields from the required set.
    """
    with admin_engine.begin() as conn:
        set_value(conn, firm, "case_type", "להגשת הגנה", status="confirmed")
    decide_every_required_field(client, headers, firm["case"])

    body = client.get(f"/cases/{firm['case']}/readiness", headers=headers).json()
    reasons = {b["field_key"]: b["reason"] for b in body["blockers"]}
    assert reasons["case_type"] == "unrecognised"
    assert body["is_ready"] is False


# ── validation flags confirmed with the firm 2026-09-29 ─────────────────────


def test_plate_equalling_an_id_in_the_same_case_is_flagged(client, headers, firm, admin_engine):
    """The real bug: a plate came back as the insured's ID missing its leading
    zero. Compared as numbers, not strings, so the missing zero doesn't hide it."""
    with admin_engine.begin() as conn:
        set_value(conn, firm, "insured_id", "056414501")
        set_value(conn, firm, "third_party_plate_number", "56414501")

    f = fields_by_key(client, headers, firm["case"])["third_party_plate_number"]
    assert "plate_matches_id" in f["attention_reasons"]


def test_a_plate_that_genuinely_differs_from_every_id_is_not_flagged(
    client, headers, firm, admin_engine
):
    with admin_engine.begin() as conn:
        set_value(conn, firm, "insured_id", "056414501")
        set_value(conn, firm, "third_party_plate_number", "4471203")

    f = fields_by_key(client, headers, firm["case"])["third_party_plate_number"]
    assert "plate_matches_id" not in f["attention_reasons"]


def test_a_zero_payment_is_always_flagged(client, headers, firm, admin_engine):
    """Confirmed unconditional: 'necessarily a mistake' in a claim case, 'a
    sign of an error' in a defence case - flagged regardless of case type or
    whether a payment document exists."""
    with admin_engine.begin() as conn:
        set_value(conn, firm, "total_paid_by_insurer", "0.00")

    f = fields_by_key(client, headers, firm["case"])["total_paid_by_insurer"]
    assert "suspicious_zero" in f["attention_reasons"]


def test_a_nonzero_payment_is_not_flagged(client, headers, firm, admin_engine):
    with admin_engine.begin() as conn:
        set_value(conn, firm, "total_paid_by_insurer", "4300")

    f = fields_by_key(client, headers, firm["case"])["total_paid_by_insurer"]
    assert "suspicious_zero" not in f["attention_reasons"]


def test_canonical_city_folds_known_aliases_only(client, headers, firm):
    """Confirmed by the firm's lawyer: Tel Aviv / Tel Aviv-Yafo and Nazareth /
    Nof HaGalil are each the same city under two names - a curated pair, not a
    general fuzzy match. Where the values actually get folded before two
    documents are compared is exercised end to end in
    test_extraction.py::test_a_known_city_alias_is_canonicalised_on_persist.
    """
    from app.services.files import canonical_city

    assert canonical_city("תל אביב-יפו") == "תל אביב"
    assert canonical_city("תל אביב יפו") == "תל אביב"
    assert canonical_city("נוף הגליל") == "נצרת"
    # Anything not on the confirmed list passes through untouched - no guessing.
    assert canonical_city("חיפה") == "חיפה"
