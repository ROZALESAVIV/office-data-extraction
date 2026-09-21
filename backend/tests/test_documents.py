"""Document upload and retrieval.

Storage is faked: these tests must not depend on a bucket, and must not leave
objects behind in a real one.
"""

import io
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import text

from app.services import storage
from tests.conftest import auth_header, make_tenant, make_user

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


class FakeStorage(dict):
    """Key -> bytes, plus a switch to make the next upload fail."""

    fail_next = False


@pytest.fixture
def fake_storage(monkeypatch):
    store = FakeStorage()

    def _upload(key, blob, content_type):
        storage._check(key)  # keep the real key validation in the loop
        if store.fail_next:
            store.fail_next = False
            raise storage.StorageError("simulated failure")
        store[key] = blob
        return key

    monkeypatch.setattr(storage, "upload", _upload)
    monkeypatch.setattr(storage, "download", lambda k: store[storage._check(k)])
    monkeypatch.setattr(storage, "delete", lambda k: store.pop(storage._check(k), None))
    monkeypatch.setattr(storage, "signed_url", lambda k, s=900: f"https://fake/{storage._check(k)}")
    return store


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
def firms(admin_engine, seeded):
    with admin_engine.begin() as conn:
        a = make_tenant(conn, "Firm A")
        b = make_tenant(conn, "Firm B")
        make_user(conn, a, "owner-a@a.test", role="owner")
        make_user(conn, a, "staff-a@a.test", role="staff")
        make_user(conn, b, "owner-b@b.test", role="owner")
    return {"a": a, "b": b}


@pytest.fixture
def owner_a(client, firms):
    return auth_header(client, "owner-a@a.test")


@pytest.fixture
def case_a(client, owner_a):
    return client.post("/cases", json={}, headers=owner_a).json()["id"]


def pdf_bytes(pages: int = 1, tag: bytes = b"") -> bytes:
    from pypdf import PdfWriter

    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=200, height=200)
    if tag:
        w.add_metadata({"/Keywords": tag.decode()})
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def upload(client, headers, case_id, name, blob):
    return client.post(
        f"/cases/{case_id}/documents",
        files=[("files", (name, blob, "application/octet-stream"))],
        headers=headers,
    )


# ── happy path ───────────────────────────────────────────────────────────────


def test_upload_pdf(client, owner_a, case_a, fake_storage):
    r = upload(client, owner_a, case_a, "claim.pdf", pdf_bytes(3))
    assert r.status_code == 201, r.text
    doc = r.json()[0]
    assert doc["file_format"] == "pdf"
    assert doc["page_count"] == 3
    assert doc["processing_status"] == "pending"
    assert doc["duplicate"] is False
    assert len(fake_storage) == 1


def test_upload_several_files_at_once(client, owner_a, case_a, fake_storage):
    r = client.post(
        f"/cases/{case_a}/documents",
        files=[
            ("files", ("a.pdf", pdf_bytes(1, b"a"), "application/pdf")),
            ("files", ("b.pdf", pdf_bytes(1, b"b"), "application/pdf")),
        ],
        headers=owner_a,
    )
    assert r.status_code == 201
    assert len(r.json()) == 2
    assert len(fake_storage) == 2


def test_storage_key_is_uuids_only(client, owner_a, case_a, fake_storage):
    """The lawyer's filename must never reach the storage layer."""
    upload(client, owner_a, case_a, "../../../etc/passwd.pdf", pdf_bytes())
    key = next(iter(fake_storage))
    assert "passwd" not in key and ".." not in key
    assert key.endswith(".pdf")
    assert len(key.split("/")) == 3


def test_filename_is_kept_for_display_but_sanitised(client, owner_a, case_a, fake_storage):
    r = upload(client, owner_a, case_a, "../../evil.pdf", pdf_bytes())
    assert r.json()[0]["file_name"] == "evil.pdf"


# ── validation ───────────────────────────────────────────────────────────────


def test_unsupported_type_is_415(client, owner_a, case_a, fake_storage):
    r = upload(client, owner_a, case_a, "notes.txt", "שלום".encode())
    assert r.status_code == 415
    assert fake_storage == {}


def test_zip_pretending_to_be_docx_is_415(client, owner_a, case_a, fake_storage):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", "<x/>")
    assert upload(client, owner_a, case_a, "sheet.docx", buf.getvalue()).status_code == 415


def test_empty_file_is_422(client, owner_a, case_a, fake_storage):
    assert upload(client, owner_a, case_a, "empty.pdf", b"").status_code == 422


def test_oversized_file_is_413(client, owner_a, case_a, fake_storage, monkeypatch):
    from app.routers import documents

    monkeypatch.setattr(documents, "MAX_FILE_BYTES", 1024)
    r = upload(client, owner_a, case_a, "big.pdf", pdf_bytes() + b"\x00" * 4096)
    assert r.status_code == 413
    assert fake_storage == {}


# ── deduplication ────────────────────────────────────────────────────────────


def test_same_file_twice_is_one_document(client, owner_a, case_a, fake_storage):
    blob = pdf_bytes(2)
    first = upload(client, owner_a, case_a, "claim.pdf", blob).json()[0]
    second = upload(client, owner_a, case_a, "claim-copy.pdf", blob).json()[0]
    assert second["id"] == first["id"]
    assert second["duplicate"] is True
    assert len(fake_storage) == 1
    assert len(client.get(f"/cases/{case_a}/documents", headers=owner_a).json()) == 1


def test_same_file_in_two_cases_is_allowed(client, owner_a, fake_storage):
    """Two firms - or two cases - may legitimately hold the same document."""
    blob = pdf_bytes(1, b"shared")
    c1 = client.post("/cases", json={}, headers=owner_a).json()["id"]
    c2 = client.post("/cases", json={}, headers=owner_a).json()["id"]
    assert upload(client, owner_a, c1, "x.pdf", blob).json()[0]["duplicate"] is False
    assert upload(client, owner_a, c2, "x.pdf", blob).json()[0]["duplicate"] is False


# ── failure handling ─────────────────────────────────────────────────────────


def test_storage_failure_leaves_no_orphan_row(client, owner_a, case_a, fake_storage, admin_engine):
    """A row pointing at bytes that were never stored is worse than an error."""
    fake_storage.fail_next = True
    r = upload(client, owner_a, case_a, "claim.pdf", pdf_bytes())
    assert r.status_code == 502
    with admin_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM documents")).scalar() == 0


# ── tenant isolation ─────────────────────────────────────────────────────────


def test_cannot_upload_into_another_tenants_case(client, firms, case_a, fake_storage):
    other = auth_header(client, "owner-b@b.test")
    assert upload(client, other, case_a, "x.pdf", pdf_bytes()).status_code == 404


def test_cannot_read_another_tenants_document(client, owner_a, case_a, firms, fake_storage):
    doc_id = upload(client, owner_a, case_a, "x.pdf", pdf_bytes()).json()[0]["id"]
    other = auth_header(client, "owner-b@b.test")
    assert client.get(f"/documents/{doc_id}", headers=other).status_code == 404
    assert client.get(f"/documents/{doc_id}/url", headers=other).status_code == 404


def test_signed_url_never_exposes_the_storage_path(client, owner_a, case_a, fake_storage):
    doc = upload(client, owner_a, case_a, "x.pdf", pdf_bytes()).json()[0]
    assert "storage_path" not in doc
    r = client.get(f"/documents/{doc['id']}/url", headers=owner_a)
    assert r.status_code == 200 and r.json()["url"].startswith("https://")


# ── permissions and case state ───────────────────────────────────────────────


def test_staff_may_upload(client, firms, case_a, fake_storage):
    """Uploading is clerical work; confirming extracted values is not."""
    staff = auth_header(client, "staff-a@a.test")
    assert upload(client, staff, case_a, "x.pdf", pdf_bytes()).status_code == 201


def test_cannot_upload_to_a_submitted_case(client, owner_a, case_a, fake_storage):
    client.patch(f"/cases/{case_a}", json={"status": "submitted"}, headers=owner_a)
    r = upload(client, owner_a, case_a, "x.pdf", pdf_bytes())
    assert r.status_code == 409


# ── classification override and delete ───────────────────────────────────────


def test_lawyer_can_reclassify(client, owner_a, case_a, fake_storage):
    doc = upload(client, owner_a, case_a, "x.pdf", pdf_bytes()).json()[0]
    types = client.get("/document-types", headers=owner_a).json()
    claim = next(t for t in types if t["type_key"] == "statement_of_claim")
    r = client.patch(
        f"/documents/{doc['id']}", json={"document_type_id": claim["id"]}, headers=owner_a
    )
    assert r.status_code == 200
    assert r.json()["document_type_key"] == "statement_of_claim"
    assert r.json()["document_type_source"] == "user"


def test_delete_is_soft(client, owner_a, case_a, fake_storage, admin_engine):
    """The stored object is kept - a case file is evidence."""
    doc = upload(client, owner_a, case_a, "x.pdf", pdf_bytes()).json()[0]
    assert client.delete(f"/documents/{doc['id']}", headers=owner_a).status_code == 204
    assert client.get(f"/documents/{doc['id']}", headers=owner_a).status_code == 404
    with admin_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM documents")).scalar() == 1
    assert len(fake_storage) == 1


# ── real sample files ────────────────────────────────────────────────────────


@pytest.mark.skipif(not SAMPLES.exists(), reason="sample case files not present")
def test_a_whole_real_case_uploads(client, owner_a, case_a, fake_storage):
    """Every file of a real referral, in one request, as the lawyer would."""
    folder = sorted(p for p in SAMPLES.iterdir() if p.is_dir())[0]
    payload = [
        ("files", (p.name, p.read_bytes(), "application/octet-stream"))
        for p in sorted(folder.iterdir())
        if p.is_file()
    ]
    r = client.post(f"/cases/{case_a}/documents", files=payload, headers=owner_a)
    assert r.status_code == 201, r.text[:500]
    docs = r.json()
    assert len(docs) == len(payload)
    assert {d["file_format"] for d in docs} <= {"pdf", "docx", "eml"}
    assert sum(1 for d in docs if d["file_format"] == "eml") == 1


def test_staff_may_not_reclassify_or_delete(client, firms, case_a, fake_storage, owner_a):
    """Re-classifying changes what gets extracted; deleting removes evidence."""
    doc = upload(client, owner_a, case_a, "x.pdf", pdf_bytes()).json()[0]
    staff = auth_header(client, "staff-a@a.test")
    types = client.get("/document-types", headers=staff).json()
    assert client.patch(
        f"/documents/{doc['id']}", json={"document_type_id": types[0]["id"]}, headers=staff
    ).status_code == 403
    assert client.delete(f"/documents/{doc['id']}", headers=staff).status_code == 403
