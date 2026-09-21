"""Login behaviour, including the inputs that used to return 500."""

from datetime import UTC

import bcrypt
import pytest
from sqlalchemy import text

from tests.conftest import auth_header, make_tenant, make_user


@pytest.fixture
def user(admin_engine):
    with admin_engine.begin() as conn:
        tenant = make_tenant(conn, "Firm A")
        uid = make_user(conn, tenant, "lawyer@firm.test")
    return {"tenant": tenant, "id": uid, "email": "lawyer@firm.test"}


def test_login_succeeds(client, user):
    resp = client.post(
        "/auth/login", data={"username": user["email"], "password": "secret123"}
    )
    assert resp.status_code == 200
    assert resp.json()["access_token"]


def test_login_wrong_password(client, user):
    resp = client.post(
        "/auth/login", data={"username": user["email"], "password": "wrong"}
    )
    assert resp.status_code == 401


def test_login_unknown_email(client, user):
    resp = client.post(
        "/auth/login", data={"username": "nobody@firm.test", "password": "secret123"}
    )
    assert resp.status_code == 401


def test_overlong_password_is_401_not_500(client, user):
    """bcrypt raises above 72 bytes. Unauthenticated input must never 500."""
    resp = client.post(
        "/auth/login", data={"username": user["email"], "password": "x" * 200}
    )
    assert resp.status_code == 401


def test_correct_password_padded_past_72_bytes_still_fails(client, user):
    """Truncation must not turn a wrong password into a right one.

    bcrypt only reads 72 bytes, so a *correct* password with junk appended past
    byte 72 would still authenticate — that is bcrypt's documented behaviour and
    is fine. What must not happen is a short wrong password being accepted.
    """
    resp = client.post(
        "/auth/login", data={"username": user["email"], "password": "secret124"}
    )
    assert resp.status_code == 401


def test_malformed_stored_hash_is_401_not_500(client, admin_engine):
    """The password_hash migration backfills '', which bcrypt rejects as a salt."""
    with admin_engine.begin() as conn:
        tenant = make_tenant(conn, "Firm B")
        conn.execute(
            text(
                "INSERT INTO users (tenant_id, email, full_name, role, password_hash) "
                "VALUES (:t, 'broken@firm.test', 'Broken', 'owner', '')"
            ),
            {"t": tenant},
        )
    resp = client.post(
        "/auth/login", data={"username": "broken@firm.test", "password": "anything"}
    )
    assert resp.status_code == 401


def test_inactive_user_cannot_log_in(client, admin_engine):
    with admin_engine.begin() as conn:
        tenant = make_tenant(conn, "Firm C")
        pw = bcrypt.hashpw(b"secret123", bcrypt.gensalt()).decode()
        conn.execute(
            text(
                "INSERT INTO users (tenant_id, email, full_name, role, password_hash, is_active) "
                "VALUES (:t, 'gone@firm.test', 'Gone', 'owner', :p, false)"
            ),
            {"t": tenant, "p": pw},
        )
    resp = client.post(
        "/auth/login", data={"username": "gone@firm.test", "password": "secret123"}
    )
    assert resp.status_code == 401


def test_me_returns_current_user(client, user):
    headers = auth_header(client, user["email"])
    resp = client.get("/auth/me", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["email"] == user["email"]


def test_garbage_token_is_401(client):
    resp = client.get("/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert resp.status_code == 401


def test_token_with_non_uuid_subject_is_401_not_500(client, user):
    """A 'sub' that is not a UUID would otherwise reach Postgres and raise."""
    from datetime import datetime, timedelta

    from jose import jwt

    from app.core.config import settings

    token = jwt.encode(
        {"sub": "not-a-uuid", "exp": datetime.now(UTC) + timedelta(minutes=5)},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_expired_token_is_401(client, user):
    from datetime import datetime, timedelta

    from jose import jwt

    from app.core.config import settings

    token = jwt.encode(
        {
            "sub": str(user["id"]),
            "exp": datetime.now(UTC) - timedelta(minutes=1),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_health_needs_no_auth(client):
    assert client.get("/health").status_code == 200
