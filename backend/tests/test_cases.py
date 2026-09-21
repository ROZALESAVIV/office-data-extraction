"""Cases API, exercised through HTTP as the non-owner application role."""

import pytest
from sqlalchemy import text

from tests.conftest import auth_header, make_tenant, make_user


@pytest.fixture
def firms(admin_engine):
    """Two firms, each with an owner, plus a staff user and a sender in firm A."""
    with admin_engine.begin() as conn:
        a = make_tenant(conn, "Firm A")
        b = make_tenant(conn, "Firm B")
        make_user(conn, a, "owner-a@a.test", role="owner")
        make_user(conn, a, "staff-a@a.test", role="staff")
        make_user(conn, b, "owner-b@b.test", role="owner")
        sender_a = conn.execute(
            text(
                "INSERT INTO senders (tenant_id, name, odcanit_prefix) "
                "VALUES (:t, 'Bank A', 'BA') RETURNING id"
            ),
            {"t": a},
        ).scalar_one()
        sender_b = conn.execute(
            text(
                "INSERT INTO senders (tenant_id, name, odcanit_prefix) "
                "VALUES (:t, 'Bank B', 'BB') RETURNING id"
            ),
            {"t": b},
        ).scalar_one()
    return {"a": a, "b": b, "sender_a": sender_a, "sender_b": sender_b}


@pytest.fixture
def owner_a(client, firms):
    return auth_header(client, "owner-a@a.test")


@pytest.fixture
def owner_b(client, firms):
    return auth_header(client, "owner-b@b.test")


def test_create_case(client, owner_a):
    resp = client.post("/cases", json={}, headers=owner_a)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "intake"
    assert body["case_number"].endswith("-0001")


def test_case_numbers_are_sequential_and_readable(client, owner_a):
    numbers = [
        client.post("/cases", json={}, headers=owner_a).json()["case_number"]
        for _ in range(3)
    ]
    suffixes = [n.split("-")[1] for n in numbers]
    assert suffixes == ["0001", "0002", "0003"], numbers


def test_case_numbers_do_not_collide_across_tenants(client, owner_a, owner_b):
    """uq_cases_tenant_case_number is per tenant, so both firms start at 0001."""
    a = client.post("/cases", json={}, headers=owner_a).json()["case_number"]
    b = client.post("/cases", json={}, headers=owner_b).json()["case_number"]
    assert a == b


def test_create_with_own_sender(client, owner_a, firms):
    resp = client.post(
        "/cases", json={"sender_id": str(firms["sender_a"])}, headers=owner_a
    )
    assert resp.status_code == 201
    assert resp.json()["sender_id"] == str(firms["sender_a"])


def test_cannot_attach_another_tenants_sender(client, owner_a, firms):
    """Foreign-key checks run as a system operation and bypass RLS, so an
    unvalidated sender_id would silently attach another firm's sender — whose
    odcanit_prefix is what gets submitted downstream."""
    resp = client.post(
        "/cases", json={"sender_id": str(firms["sender_b"])}, headers=owner_a
    )
    assert resp.status_code == 422, resp.text


def test_list_only_shows_own_tenant(client, owner_a, owner_b):
    client.post("/cases", json={}, headers=owner_a)
    client.post("/cases", json={}, headers=owner_b)
    a_ids = {c["id"] for c in client.get("/cases", headers=owner_a).json()}
    b_ids = {c["id"] for c in client.get("/cases", headers=owner_b).json()}
    assert len(a_ids) == 1 and len(b_ids) == 1
    assert a_ids.isdisjoint(b_ids)


def test_cross_tenant_get_is_404(client, owner_a, owner_b):
    case_id = client.post("/cases", json={}, headers=owner_a).json()["id"]
    assert client.get(f"/cases/{case_id}", headers=owner_b).status_code == 404


def test_cross_tenant_patch_is_404(client, owner_a, owner_b):
    case_id = client.post("/cases", json={}, headers=owner_a).json()["id"]
    resp = client.patch(
        f"/cases/{case_id}", json={"status": "closed"}, headers=owner_b
    )
    assert resp.status_code == 404


def test_cross_tenant_delete_is_404(client, owner_a, owner_b):
    case_id = client.post("/cases", json={}, headers=owner_a).json()["id"]
    assert client.delete(f"/cases/{case_id}", headers=owner_b).status_code == 404


def test_patch_updates_status(client, owner_a):
    case_id = client.post("/cases", json={}, headers=owner_a).json()["id"]
    resp = client.patch(
        f"/cases/{case_id}", json={"status": "ready_for_review"}, headers=owner_a
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready_for_review"


def test_patch_rejects_unknown_status(client, owner_a):
    case_id = client.post("/cases", json={}, headers=owner_a).json()["id"]
    resp = client.patch(f"/cases/{case_id}", json={"status": "banana"}, headers=owner_a)
    assert resp.status_code == 422


def test_delete_is_soft(client, owner_a, admin_engine):
    case_id = client.post("/cases", json={}, headers=owner_a).json()["id"]
    assert client.delete(f"/cases/{case_id}", headers=owner_a).status_code == 204
    assert client.get(f"/cases/{case_id}", headers=owner_a).status_code == 404
    with admin_engine.connect() as conn:
        deleted_at = conn.execute(
            text("SELECT deleted_at FROM cases WHERE id = :i"), {"i": case_id}
        ).scalar()
    assert deleted_at is not None, "row was hard-deleted"


def test_staff_cannot_create_a_case(client, firms):
    headers = auth_header(client, "staff-a@a.test")
    assert client.post("/cases", json={}, headers=headers).status_code == 403


def test_staff_can_read_cases(client, firms, owner_a):
    client.post("/cases", json={}, headers=owner_a)
    headers = auth_header(client, "staff-a@a.test")
    resp = client.get("/cases", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_staff_cannot_change_status(client, firms, owner_a):
    case_id = client.post("/cases", json={}, headers=owner_a).json()["id"]
    headers = auth_header(client, "staff-a@a.test")
    resp = client.patch(
        f"/cases/{case_id}", json={"status": "submitted"}, headers=headers
    )
    assert resp.status_code == 403


def test_unauthenticated_is_401(client):
    assert client.get("/cases").status_code == 401


def test_mutations_are_audited(client, owner_a, admin_engine):
    case_id = client.post("/cases", json={}, headers=owner_a).json()["id"]
    client.patch(f"/cases/{case_id}", json={"status": "closed"}, headers=owner_a)
    client.delete(f"/cases/{case_id}", headers=owner_a)
    with admin_engine.connect() as conn:
        actions = [
            r[0]
            for r in conn.execute(
                text("SELECT action FROM audit_log WHERE case_id = :c ORDER BY created_at"),
                {"c": case_id},
            )
        ]
    assert actions == ["case.created", "case.updated", "case.deleted"]
