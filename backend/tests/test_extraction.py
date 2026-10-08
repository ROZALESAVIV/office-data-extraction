"""The extraction pipeline, with a fake model.

Covers classification, filtering, candidate persistence, idempotency and
failure handling. No API calls, no cost.
"""

import io
from pathlib import Path

import pytest
from sqlalchemy import text

from app.services import extraction, llm, storage
from tests.conftest import auth_header, make_tenant, make_user
from tests.fakes import FakeLLM, classified, extracted

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


def pdf_bytes(pages: int = 2, tag: str = "") -> bytes:
    from pypdf import PdfWriter

    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=200, height=200)
    if tag:
        w.add_metadata({"/Keywords": tag})
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


@pytest.fixture
def seeded(admin_engine):
    import os
    import subprocess
    import sys

    r = subprocess.run(
        [sys.executable, "-m", "scripts.seed_reference"],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True, text=True, env={**os.environ},
    )
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.fixture
def store(monkeypatch):
    data = {}
    monkeypatch.setattr(storage, "upload", lambda k, b, ct: (data.__setitem__(k, b), k)[1])
    monkeypatch.setattr(storage, "download", lambda k: data[k])
    monkeypatch.setattr(storage, "signed_url", lambda k, s=900: f"https://fake/{k}")
    monkeypatch.setattr(storage, "delete", lambda k: data.pop(k, None))
    return data


@pytest.fixture
def firm(admin_engine, seeded):
    with admin_engine.begin() as conn:
        t = make_tenant(conn, "Firm A")
        make_user(conn, t, "owner@a.test", role="owner")
    return t


@pytest.fixture
def headers(client, firm):
    return auth_header(client, "owner@a.test")


@pytest.fixture
def case_id(client, headers):
    return client.post("/cases", json={}, headers=headers).json()["id"]


def upload(client, headers, case_id, name, blob):
    """Upload without letting the real background task run."""
    from app.routers import documents

    original = documents.extraction.run
    documents.extraction.run = lambda *a, **k: None
    try:
        return client.post(
            f"/cases/{case_id}/documents",
            files=[("files", (name, blob, "application/octet-stream"))],
            headers=headers,
        ).json()[0]
    finally:
        documents.extraction.run = original


def field_values(admin_engine, case_id):
    with admin_engine.connect() as conn:
        return {
            r.field_key: r
            for r in conn.execute(
                text("""SELECT cf.field_key, v.value, v.extracted_value, v.status,
                               v.confidence_score, v.has_conflict, v.source_page
                        FROM case_field_values v JOIN case_fields cf ON cf.id = v.field_id
                        WHERE v.case_id = :c"""),
                {"c": case_id},
            )
        }


# ── classification and filtering ─────────────────────────────────────────────


def test_photographs_are_classified_and_skipped(client, headers, case_id, firm, store, admin_engine):
    """Most of a claim file is photographs. They are stored, never read."""
    doc = upload(client, headers, case_id, "damage.pdf", pdf_bytes())
    fake = FakeLLM({llm.CLASSIFY_TOOL_NAME: classified("damage_photos")})
    report = extraction.run(doc["id"], firm, client=fake)

    assert report.status == "skipped"
    assert report.candidates == 0
    # classified once, never sent for extraction
    assert [c["tool"] for c in fake.calls] == [llm.CLASSIFY_TOOL_NAME]


def test_low_confidence_classification_is_not_trusted(client, headers, case_id, firm, store):
    doc = upload(client, headers, case_id, "mystery.pdf", pdf_bytes())
    fake = FakeLLM({llm.CLASSIFY_TOOL_NAME: classified("statement_of_claim", confidence=0.3)})
    report = extraction.run(doc["id"], firm, client=fake)
    assert report.status == "skipped", "an unsure label must not drive extraction"


def test_classification_uses_one_page_and_low_effort(client, headers, case_id, firm, store):
    doc = upload(client, headers, case_id, "x.pdf", pdf_bytes(pages=30))
    fake = FakeLLM({llm.CLASSIFY_TOOL_NAME: classified("damage_photos")})
    extraction.run(doc["id"], firm, client=fake)
    assert fake.calls[0]["effort"] == llm.CLASSIFY_EFFORT


def test_only_the_mapped_fields_are_requested(client, headers, case_id, firm, store):
    """A focused prompt is the whole point: 7 fields, not 42."""
    doc = upload(client, headers, case_id, "policy.pdf", pdf_bytes())
    fake = FakeLLM({
        llm.CLASSIFY_TOOL_NAME: classified("policy_schedule"),
        llm.EXTRACT_TOOL_NAME: extracted(),
    })
    extraction.run(doc["id"], firm, client=fake)
    asked = fake.calls[1]["field_keys"]
    assert "insured_id" in asked
    assert "court_name" not in asked, "a policy schedule has no court in it"
    assert len(asked) < 15


def test_document_block_is_first_and_cached(client, headers, case_id, firm, store):
    """Cache hits depend on the stable document block preceding the field list."""
    doc = upload(client, headers, case_id, "policy.pdf", pdf_bytes())
    fake = FakeLLM({
        llm.CLASSIFY_TOOL_NAME: classified("policy_schedule"),
        llm.EXTRACT_TOOL_NAME: extracted(),
    })
    extraction.run(doc["id"], firm, client=fake)
    for call in fake.calls:
        assert call["content_types"][0] == "document"
        assert call["first_block_cached"] is True


# ── candidates ───────────────────────────────────────────────────────────────


def test_extracted_values_become_candidates_and_an_answer(
    client, headers, case_id, firm, store, admin_engine
):
    doc = upload(client, headers, case_id, "claim.pdf", pdf_bytes())
    fake = FakeLLM({
        llm.CLASSIFY_TOOL_NAME: classified("statement_of_claim"),
        llm.EXTRACT_TOOL_NAME: extracted(
            ("court_name", "בית משפט השלום בכפר סבא", 0.97, 1, "בית משפט השלום בכפר סבא"),
            ("claim_amount", "47,300 ₪", 0.85, 2, "סכום התביעה 47,300 ₪"),
        ),
    })
    report = extraction.run(doc["id"], firm, client=fake)

    assert report.status == "extracted"
    assert report.candidates == 2
    values = field_values(admin_engine, case_id)
    assert values["court_name"].value == "בית משפט השלום בכפר סבא"
    assert values["claim_amount"].value == "47300", "amounts are normalised"
    assert values["court_name"].status == "pending_review"


def test_null_values_are_not_stored(client, headers, case_id, firm, store, admin_engine):
    """"Not found" is a correct answer, not a row."""
    doc = upload(client, headers, case_id, "claim.pdf", pdf_bytes())
    fake = FakeLLM({
        llm.CLASSIFY_TOOL_NAME: classified("statement_of_claim"),
        llm.EXTRACT_TOOL_NAME: extracted(
            ("court_name", "השלום", 0.9, 1, "השלום"),
            ("claim_amount", None, 0.0, None, None),
        ),
    })
    extraction.run(doc["id"], firm, client=fake)
    assert "claim_amount" not in field_values(admin_engine, case_id)


def test_rerunning_is_idempotent(client, headers, case_id, firm, store, admin_engine):
    doc = upload(client, headers, case_id, "claim.pdf", pdf_bytes())
    script = lambda: FakeLLM({  # noqa: E731
        llm.CLASSIFY_TOOL_NAME: classified("statement_of_claim"),
        llm.EXTRACT_TOOL_NAME: extracted(("court_name", "השלום", 0.9, 1, "השלום")),
    })
    extraction.run(doc["id"], firm, client=script())
    with admin_engine.connect() as conn:
        first = conn.execute(text("SELECT count(*) FROM field_candidates")).scalar()

    with admin_engine.begin() as conn:  # release the attempt cap for the re-run
        conn.execute(text("UPDATE documents SET extraction_attempts = 0"))
    extraction.run(doc["id"], firm, client=script())
    with admin_engine.connect() as conn:
        second = conn.execute(text("SELECT count(*) FROM field_candidates")).scalar()
    assert first == second == 1, "a re-run replaces candidates, it does not accumulate"


# ── failure handling ─────────────────────────────────────────────────────────


def test_total_failure_marks_the_document_not_the_process(
    client, headers, case_id, firm, store, admin_engine
):
    doc = upload(client, headers, case_id, "claim.pdf", pdf_bytes())
    fake = FakeLLM({
        llm.CLASSIFY_TOOL_NAME: classified("statement_of_claim"),
        llm.EXTRACT_TOOL_NAME: llm.LLMError("boom"),
    })
    report = extraction.run(doc["id"], firm, client=fake)

    assert report.status == "failed"
    with admin_engine.connect() as conn:
        row = conn.execute(
            text("SELECT processing_status, error_message FROM documents")
        ).one()
    assert row.processing_status == "failed"
    assert row.error_message


def test_run_never_raises(client, headers, case_id, firm, store):
    """BackgroundTasks discards exceptions silently, so run() must not throw."""
    doc = upload(client, headers, case_id, "claim.pdf", pdf_bytes())

    class Exploding:
        def call_tool(self, **kw):
            raise RuntimeError("unexpected")

    report = extraction.run(doc["id"], firm, client=Exploding())
    assert report.status == "failed"


def test_a_second_worker_does_not_steal_a_live_lease(client, headers, case_id, firm, store):
    doc = upload(client, headers, case_id, "claim.pdf", pdf_bytes())
    fake = FakeLLM({llm.CLASSIFY_TOOL_NAME: classified("damage_photos")})
    extraction.run(doc["id"], firm, client=fake)
    # already terminal; a second run must not redo the work
    again = extraction.run(doc["id"], firm, client=FakeLLM())
    assert again.status in ("skipped",)


# ── the referral email ───────────────────────────────────────────────────────


@pytest.mark.skipif(not SAMPLES.exists(), reason="sample case files not present")
def test_referral_email_is_parsed_without_the_model(
    client, headers, case_id, firm, store, admin_engine
):
    """Seven fields, full confidence, and not a single API call."""
    eml = next(SAMPLES.glob("*/*.eml"))
    doc = upload(client, headers, case_id, eml.name, eml.read_bytes())
    fake = FakeLLM()
    report = extraction.run(doc["id"], firm, client=fake)

    assert fake.calls == [], "the email must not reach the model at all"
    assert report.status == "extracted"
    assert report.cost_usd == 0.0

    values = field_values(admin_engine, case_id)
    for key in ("direct_claim_number", "direct_policy_number", "accident_date",
                "insured_plate_number", "insured_name", "case_type"):
        assert key in values, f"{key} missing"
        assert float(values[key].confidence_score) == 1.0


def test_reprocess_re_runs_a_finished_document(
    client, headers, case_id, firm, store, admin_engine
):
    """Explicit re-run is allowed - that is what the lawyer's override needs."""
    doc = upload(client, headers, case_id, "claim.pdf", pdf_bytes())
    extraction.run(doc["id"], firm,
                   client=FakeLLM({llm.CLASSIFY_TOOL_NAME: classified("damage_photos")}))

    from app.routers import documents as documents_router

    original = documents_router.extraction.run
    documents_router.extraction.run = lambda *a, **k: None
    try:
        r = client.post(f"/documents/{doc['id']}/reprocess", headers=headers)
    finally:
        documents_router.extraction.run = original
    assert r.status_code == 200
    assert r.json()["processing_status"] == "pending"

    fake = FakeLLM({
        llm.CLASSIFY_TOOL_NAME: classified("statement_of_claim"),
        llm.EXTRACT_TOOL_NAME: extracted(("court_name", "השלום", 0.9, 1, "השלום")),
    })
    report = extraction.run(doc["id"], firm, client=fake)
    assert report.status == "extracted"
    assert field_values(admin_engine, case_id)["court_name"].value == "השלום"


# ── navigation: long documents are narrowed before extraction ────────────────


def test_short_documents_skip_navigation(client, headers, case_id, firm, store):
    doc = upload(client, headers, case_id, "policy.pdf", pdf_bytes(pages=3))
    fake = FakeLLM({
        llm.CLASSIFY_TOOL_NAME: classified("policy_schedule"),
        llm.EXTRACT_TOOL_NAME: extracted(),
    })
    extraction.run(doc["id"], firm, client=fake)
    assert llm.NAVIGATE_TOOL_NAME not in [c["tool"] for c in fake.calls]


def test_long_documents_are_navigated_then_narrowed(
    client, headers, case_id, firm, store, admin_engine
):
    """A 48-page pleading bundle is 4 pages of claim and 44 of exhibits."""
    doc = upload(client, headers, case_id, "claim.pdf", pdf_bytes(pages=48))
    fake = FakeLLM({
        llm.CLASSIFY_TOOL_NAME: classified("statement_of_claim"),
        llm.NAVIGATE_TOOL_NAME: {
            "content_first_page": 1, "content_last_page": 5,
            "confidence": 0.9, "reason": "exhibits start at page 6",
        },
        llm.EXTRACT_TOOL_NAME: extracted(("court_name", "השלום", 0.9, 1, "השלום")),
    })
    extraction.run(doc["id"], firm, client=fake)

    tools = [c["tool"] for c in fake.calls]
    assert tools == [llm.CLASSIFY_TOOL_NAME, llm.NAVIGATE_TOOL_NAME, llm.EXTRACT_TOOL_NAME]
    # 5 content pages fit in one window; without navigation this would be three
    assert tools.count(llm.EXTRACT_TOOL_NAME) == 1


def test_unsure_navigation_falls_back_to_a_capped_prefix(
    client, headers, case_id, firm, store
):
    """Guessing a range is worse than reading a bounded prefix."""
    doc = upload(client, headers, case_id, "claim.pdf", pdf_bytes(pages=100))
    fake = FakeLLM({
        llm.CLASSIFY_TOOL_NAME: classified("statement_of_claim"),
        llm.NAVIGATE_TOOL_NAME: {
            "content_first_page": 1, "content_last_page": 100,
            "confidence": 0.2, "reason": "cannot tell",
        },
        llm.EXTRACT_TOOL_NAME: [extracted(), extracted()],
    })
    extraction.run(doc["id"], firm, client=fake)
    windows = [c for c in fake.calls if c["tool"] == llm.EXTRACT_TOOL_NAME]
    assert len(windows) == extraction.MAX_EXTRACT_PAGES // extraction.PAGE_WINDOW


def test_an_absurdly_long_range_is_capped(client, headers, case_id, firm, store):
    """One real sample is 186 pages of damage photographs."""
    doc = upload(client, headers, case_id, "photos.pdf", pdf_bytes(pages=186))
    fake = FakeLLM({
        llm.CLASSIFY_TOOL_NAME: classified("statement_of_claim"),
        llm.NAVIGATE_TOOL_NAME: {
            "content_first_page": 1, "content_last_page": 186,
            "confidence": 0.95, "reason": "all content",
        },
        llm.EXTRACT_TOOL_NAME: [extracted() for _ in range(20)],
    })
    extraction.run(doc["id"], firm, client=fake)
    windows = [c for c in fake.calls if c["tool"] == llm.EXTRACT_TOOL_NAME]
    assert len(windows) * extraction.PAGE_WINDOW <= extraction.MAX_EXTRACT_PAGES


def test_a_known_city_alias_is_canonicalised_on_persist(
    client, headers, case_id, firm, store, admin_engine
):
    """'תל אביב-יפו' and 'תל אביב' are the same city, confirmed by the firm's
    lawyer - folded to one spelling at persist time so a second document
    naming the same court in the other spelling doesn't read as a conflict."""
    doc = upload(client, headers, case_id, "claim.pdf", pdf_bytes())
    fake = FakeLLM({
        llm.CLASSIFY_TOOL_NAME: classified("statement_of_claim"),
        llm.EXTRACT_TOOL_NAME: extracted(
            ("court_city", "תל אביב-יפו", 0.9, 1, "בית משפט השלום בתל אביב-יפו"),
        ),
    })
    extraction.run(doc["id"], firm, client=fake)

    values = field_values(admin_engine, case_id)
    assert values["court_city"].value == "תל אביב"


# ── subrogation party mapping, confirmed with the firm 2026-09-29 ───────────


def _set_case_type(admin_engine, firm, case_id, value):
    with admin_engine.begin() as conn:
        field_id = conn.execute(
            text("SELECT id FROM case_fields WHERE field_key = 'case_type'")
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO case_field_values "
                "(tenant_id, case_id, field_id, value, extracted_value, status) "
                "VALUES (:t, :c, :f, :v, :v, 'pending_review')"
            ),
            {"t": firm, "c": case_id, "f": field_id, "v": value},
        )


def _attach_sender(admin_engine, firm, case_id, name):
    with admin_engine.begin() as conn:
        sender_id = conn.execute(
            text(
                "INSERT INTO senders (tenant_id, name, odcanit_prefix) "
                "VALUES (:t, :n, '555') RETURNING id"
            ),
            {"t": firm, "n": name},
        ).scalar_one()
        conn.execute(
            text("UPDATE cases SET sender_id = :s WHERE id = :c"),
            {"s": sender_id, "c": case_id},
        )


def test_subrogation_plaintiff_is_populated_from_the_sender(
    case_id, firm, admin_engine, admin_session
):
    """plaintiff_1 in a claim case is the referring insurer - a structural
    fact already known from the case's sender, not re-derived from a letter."""
    _set_case_type(admin_engine, firm, case_id, "תביעה")
    _attach_sender(admin_engine, firm, case_id, "ביטוח ישיר")

    extraction.resolve_case_fields(admin_session, case_id, firm)
    admin_session.commit()

    values = field_values(admin_engine, case_id)
    assert values["plaintiff_1_name"].value == "ביטוח ישיר"
    assert float(values["plaintiff_1_name"].confidence_score) == 1.0


def test_a_defence_case_s_plaintiff_is_not_touched_by_the_sender(
    case_id, firm, admin_engine, admin_session
):
    """Only a claim case's plaintiff is the referring insurer - in a defence
    case plaintiff_1 is whoever sued us, read from the pleading instead."""
    _set_case_type(admin_engine, firm, case_id, "הגנה")
    _attach_sender(admin_engine, firm, case_id, "ביטוח ישיר")

    extraction.resolve_case_fields(admin_session, case_id, firm)
    admin_session.commit()

    values = field_values(admin_engine, case_id)
    assert "plaintiff_1_name" not in values


def test_a_confirmed_plaintiff_is_never_overwritten_by_the_sender(
    case_id, firm, admin_engine, admin_session
):
    """Once a lawyer has decided, this mechanical fill-in must back off -
    same freeze rule as every other resolved field (DECISIONS 7)."""
    _set_case_type(admin_engine, firm, case_id, "תביעה")
    _attach_sender(admin_engine, firm, case_id, "ביטוח ישיר")
    with admin_engine.begin() as conn:
        field_id = conn.execute(
            text("SELECT id FROM case_fields WHERE field_key = 'plaintiff_1_name'")
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO case_field_values "
                "(tenant_id, case_id, field_id, value, extracted_value, status, reviewed_at) "
                "VALUES (:t, :c, :f, 'שם שתוקן ידנית', NULL, 'edited', now())"
            ),
            {"t": firm, "c": case_id, "f": field_id},
        )

    extraction.resolve_case_fields(admin_session, case_id, firm)
    admin_session.commit()

    values = field_values(admin_engine, case_id)
    assert values["plaintiff_1_name"].value == "שם שתוקן ידנית"


def test_no_sender_means_no_crash_and_no_value(case_id, firm, admin_engine, admin_session):
    _set_case_type(admin_engine, firm, case_id, "תביעה")
    # No sender attached - cases.sender_id stays NULL.

    extraction.resolve_case_fields(admin_session, case_id, firm)
    admin_session.commit()

    values = field_values(admin_engine, case_id)
    assert "plaintiff_1_name" not in values


def test_the_same_field_found_in_two_windows_does_not_crash_the_document(
    client, headers, case_id, firm, store, admin_engine
):
    """Found as a live bug on real data: a 26-page pleading stated the claim
    number near the top and repeated it lower down, in two different
    extraction windows. Inserting both candidates violated the one-row-per-
    (document, field) constraint and failed the entire document, losing every
    field it would otherwise have contributed - not just the duplicate one."""
    doc = upload(client, headers, case_id, "long.pdf", pdf_bytes(pages=35))
    fake = FakeLLM({
        llm.CLASSIFY_TOOL_NAME: classified("statement_of_claim"),
        llm.NAVIGATE_TOOL_NAME: {
            "content_first_page": 1, "content_last_page": 35,
            "confidence": 0.95, "reason": "all content",
        },
        llm.EXTRACT_TOOL_NAME: [
            # Window 1: pages 1-20. The court name, confidently, near the top.
            extracted(("court_name", "בית משפט השלום", 0.9, 1, "בית משפט השלום")),
            # Window 2: pages 21-35 (window-local page 1 = document page 21).
            # Same fact, repeated, read with less confidence further down.
            extracted(("court_name", "בית משפט השלום", 0.65, 1, "בבית משפט השלום")),
        ],
    })
    report = extraction.run(doc["id"], firm, client=fake)

    assert report.status == "extracted", "must not fail the whole document"
    values = field_values(admin_engine, case_id)
    assert values["court_name"].value == "בית משפט השלום"
    # The higher-confidence, earlier occurrence won.
    assert values["court_name"].source_page == 1
