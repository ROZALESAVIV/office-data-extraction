"""Test harness.

Two things here are load-bearing and should not be "simplified" away:

1. **A real PostgreSQL.** Row-level security, FORCE RLS, triggers, composite
   foreign keys and advisory locks do not exist in SQLite. An isolation suite
   that runs on SQLite proves nothing.

2. **Two roles.** Migrations and fixtures run as the owner; every request runs
   as a non-owner role without BYPASSRLS. If the tests ran as the owner, every
   isolation assertion below would pass whether or not the policies work — which
   is exactly how the original "10 passing tests" claim came about.

The connection settings are forced into the environment before any application
module is imported, so a developer's real .env (pointing at a live Supabase
project) can never be picked up by the test suite.
"""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

APP_ROLE = "ode_app"
APP_ROLE_PASSWORD = "ode_app_test_pw"

ADMIN_URL = os.environ.get(
    "TEST_DATABASE_ADMIN_URL",
    "postgresql://postgres:testpw@localhost:55432/ode_test",
)
APP_URL = os.environ.get(
    "TEST_DATABASE_URL",
    f"postgresql://{APP_ROLE}:{APP_ROLE_PASSWORD}@localhost:55432/ode_test",
)

os.environ["DATABASE_URL"] = APP_URL
os.environ["DATABASE_ADMIN_URL"] = ADMIN_URL
os.environ["APP_DB_ROLE"] = APP_ROLE
os.environ["APP_DB_PASSWORD"] = APP_ROLE_PASSWORD
os.environ["JWT_SECRET"] = "test-secret-not-for-production"
os.environ["SUPABASE_URL"] = ""
os.environ["SUPABASE_SERVICE_KEY"] = ""
# Every test that reaches extraction.run() passes an explicit FakeLLM, so the
# real key is never used today - but a future test that forgets to pass one
# would silently fall through to llm.AnthropicLLM() and make a real, billed
# call using whatever is in backend/.env. Blanking it here makes that fail
# loudly (a clear auth error) instead of quietly spending money.
os.environ["ANTHROPIC_API_KEY"] = ""

import bcrypt  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402


@pytest.fixture(scope="session")
def admin_engine():
    engine = create_engine(ADMIN_URL, future=True)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - environment problem
        pytest.skip(f"No test PostgreSQL at {ADMIN_URL}: {exc}")
    return engine


@pytest.fixture(scope="session", autouse=True)
def migrated_db(admin_engine):
    """Rebuild the schema from scratch and run every migration."""
    with admin_engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        env={**os.environ},
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"alembic upgrade head failed:\n{result.stdout}\n{result.stderr}"
        )
    return True


@pytest.fixture(scope="session")
def app_engine(migrated_db):
    """Engine for the non-owner application role — subject to RLS."""
    return create_engine(APP_URL, future=True)


@pytest.fixture
def admin_session(admin_engine, migrated_db):
    session = sessionmaker(bind=admin_engine)()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture(autouse=True)
def clean_tables(admin_engine, migrated_db):
    """Truncate tenant data between tests, as the owner."""
    yield
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE audit_log, odcanit_submissions, case_field_values, "
                "documents, cases, senders, users, tenants "
                "RESTART IDENTITY CASCADE"
            )
        )


def make_tenant(conn, name: str) -> uuid.UUID:
    return conn.execute(
        text("INSERT INTO tenants (name) VALUES (:n) RETURNING id"), {"n": name}
    ).scalar_one()


def make_user(conn, tenant_id, email: str, password: str = "secret123", role: str = "owner"):
    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    return conn.execute(
        text(
            "INSERT INTO users (tenant_id, email, full_name, role, password_hash) "
            "VALUES (:t, :e, :f, :r, :p) RETURNING id"
        ),
        {"t": tenant_id, "e": email, "f": email, "r": role, "p": pw_hash},
    ).scalar_one()


def make_case(conn, tenant_id, case_number: str, created_by=None):
    return conn.execute(
        text(
            "INSERT INTO cases (tenant_id, case_number, status, created_by) "
            "VALUES (:t, :c, 'intake', :u) RETURNING id"
        ),
        {"t": tenant_id, "c": case_number, "u": created_by},
    ).scalar_one()


@pytest.fixture
def two_tenants(admin_engine):
    """Tenant A and tenant B, each with an owner user and one case."""
    with admin_engine.begin() as conn:
        a = make_tenant(conn, "Firm A")
        b = make_tenant(conn, "Firm B")
        ua = make_user(conn, a, "a@firm-a.test")
        ub = make_user(conn, b, "b@firm-b.test")
        ca = make_case(conn, a, "2026-0001", ua)
        cb = make_case(conn, b, "2026-0001", ub)
    return {
        "a": {"tenant": a, "user": ua, "case": ca},
        "b": {"tenant": b, "user": ub, "case": cb},
    }


@pytest.fixture
def client(app_engine):
    """FastAPI test client wired to the non-owner application role."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


def auth_header(client, email: str, password: str = "secret123") -> dict:
    resp = client.post("/auth/login", data={"username": email, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}
