"""Senders API."""

import pytest

from tests.conftest import auth_header, make_tenant, make_user


@pytest.fixture
def firms(admin_engine):
    with admin_engine.begin() as conn:
        a = make_tenant(conn, "Firm A")
        b = make_tenant(conn, "Firm B")
        make_user(conn, a, "owner-a@a.test", role="owner")
        make_user(conn, a, "lawyer-a@a.test", role="lawyer")
        make_user(conn, b, "owner-b@b.test", role="owner")
    return {"a": a, "b": b}


@pytest.fixture
def owner_a(client, firms):
    return auth_header(client, "owner-a@a.test")


def test_create_and_list(client, owner_a):
    resp = client.post(
        "/senders", json={"name": "Bank Leumi", "odcanit_prefix": "LEU"}, headers=owner_a
    )
    assert resp.status_code == 201, resp.text
    listed = client.get("/senders", headers=owner_a).json()
    assert [s["name"] for s in listed] == ["Bank Leumi"]


def test_odcanit_prefix_is_not_exposed(client, owner_a):
    """The prefix drives Odcanit submission; it is configuration, not UI data."""
    resp = client.post(
        "/senders", json={"name": "Bank Leumi", "odcanit_prefix": "LEU"}, headers=owner_a
    )
    assert "odcanit_prefix" not in resp.json()


def test_duplicate_name_is_409_not_500(client, owner_a):
    payload = {"name": "Bank Leumi", "odcanit_prefix": "LEU"}
    assert client.post("/senders", json=payload, headers=owner_a).status_code == 201
    assert client.post("/senders", json=payload, headers=owner_a).status_code == 409


def test_same_name_allowed_in_different_tenants(client, firms, owner_a):
    payload = {"name": "Bank Leumi", "odcanit_prefix": "LEU"}
    assert client.post("/senders", json=payload, headers=owner_a).status_code == 201
    owner_b = auth_header(client, "owner-b@b.test")
    assert client.post("/senders", json=payload, headers=owner_b).status_code == 201


def test_list_is_tenant_scoped(client, firms, owner_a):
    client.post(
        "/senders", json={"name": "Bank Leumi", "odcanit_prefix": "LEU"}, headers=owner_a
    )
    owner_b = auth_header(client, "owner-b@b.test")
    assert client.get("/senders", headers=owner_b).json() == []


def test_only_owner_may_create(client, firms):
    headers = auth_header(client, "lawyer-a@a.test")
    resp = client.post(
        "/senders", json={"name": "X", "odcanit_prefix": "X"}, headers=headers
    )
    assert resp.status_code == 403


def test_blank_name_is_rejected(client, owner_a):
    resp = client.post(
        "/senders", json={"name": "", "odcanit_prefix": "LEU"}, headers=owner_a
    )
    assert resp.status_code == 422
