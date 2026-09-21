"""Proof that tenant isolation is actually enforced.

These are the gate for everything else in the product. A law firm's documents
are privileged material; a cross-tenant read is not a bug report, it is a
disclosure incident.

The structural tests exist to catch the *next* developer, not just today's
defect: they discover tables from the live catalogue, so adding a tenant-scoped
table without a policy fails the suite on its own.
"""


import pytest
from sqlalchemy import text

from tests.conftest import APP_ROLE

# Tables carrying tenant data. Kept explicit as a cross-check against the
# catalogue-driven discovery in test_all_tenant_tables_force_rls.
TENANT_TABLES = [
    "senders",
    "cases",
    "documents",
    "case_field_values",
    "odcanit_submissions",
    "audit_log",
]


def set_tenant(conn, tenant_id):
    conn.execute(
        text("SELECT set_config('app.current_tenant_id', :t, true)"),
        {"t": str(tenant_id)},
    )


# ── structural ───────────────────────────────────────────────────────────────


def test_app_role_is_not_the_owner(app_engine):
    with app_engine.connect() as conn:
        assert conn.execute(text("SELECT current_user")).scalar() == APP_ROLE


def test_app_role_cannot_bypass_rls(app_engine):
    """A role with BYPASSRLS or superuser silently defeats every policy."""
    with app_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT rolbypassrls, rolsuper FROM pg_roles "
                "WHERE rolname = current_user"
            )
        ).one()
    assert row.rolbypassrls is False
    assert row.rolsuper is False


# The single deliberate exemption: login has to find a user by email before any
# tenant context can exist, so `users` cannot be behind a tenant policy. Adding
# to this set is a security decision and must be argued for, not convenient.
RLS_EXEMPT_TABLES = {"users"}


def _tenant_scoped_tables(conn) -> list[str]:
    return [
        r[0]
        for r in conn.execute(
            text(
                "SELECT table_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND column_name = 'tenant_id' "
                "ORDER BY table_name"
            )
        )
    ]


def test_all_tenant_tables_force_rls(admin_engine):
    """Every table with a tenant_id must have RLS enabled *and* forced.

    ENABLE alone is not enough: Postgres exempts the table owner from its own
    policies unless FORCE is also set. Tables are discovered from the live
    catalogue, so a new tenant-scoped table without a policy fails this test
    without anyone having to remember to update a list.
    """
    with admin_engine.connect() as conn:
        tables = _tenant_scoped_tables(conn)
        assert tables, "no tenant-scoped tables found — schema not migrated?"
        unprotected = []
        for table in tables:
            if table in RLS_EXEMPT_TABLES:
                continue
            row = conn.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE oid = to_regclass('public.' || :t)"
                ),
                {"t": table},
            ).one()
            if not (row.relrowsecurity and row.relforcerowsecurity):
                unprotected.append(table)
    assert unprotected == [], f"tables without forced RLS: {unprotected}"


def test_rls_exemptions_are_only_the_documented_ones(admin_engine):
    """Guard the exemption list itself, so it cannot quietly grow."""
    with admin_engine.connect() as conn:
        tables = _tenant_scoped_tables(conn)
        actually_exempt = {
            t
            for t in tables
            if not conn.execute(
                text(
                    "SELECT relforcerowsecurity FROM pg_class "
                    "WHERE oid = to_regclass('public.' || :t)"
                ),
                {"t": t},
            ).scalar()
        }
    assert actually_exempt == RLS_EXEMPT_TABLES


def test_every_policy_has_with_check(admin_engine):
    """USING is not applied to INSERT — without WITH CHECK a user can write
    rows carrying another tenant's id."""
    with admin_engine.connect() as conn:
        missing = [
            r[0]
            for r in conn.execute(
                text(
                    "SELECT polrelid::regclass::text FROM pg_policy "
                    "WHERE polwithcheck IS NULL AND polcmd = '*'"
                )
            )
        ]
    assert missing == [], f"policies without WITH CHECK: {missing}"


# ── behavioural ──────────────────────────────────────────────────────────────


def test_no_tenant_context_sees_nothing(app_engine, two_tenants):
    """Fail closed: an unset tenant must reveal nothing, not everything."""
    with app_engine.connect() as conn:
        count = conn.execute(text("SELECT count(*) FROM cases")).scalar()
    assert count == 0


def test_select_isolation(app_engine, two_tenants):
    with app_engine.connect() as conn:
        set_tenant(conn, two_tenants["a"]["tenant"])
        ids = [r[0] for r in conn.execute(text("SELECT id FROM cases"))]
    assert ids == [two_tenants["a"]["case"]]


def test_update_isolation(app_engine, two_tenants):
    with app_engine.begin() as conn:
        set_tenant(conn, two_tenants["a"]["tenant"])
        result = conn.execute(
            text("UPDATE cases SET status = 'closed' WHERE id = :id"),
            {"id": two_tenants["b"]["case"]},
        )
    assert result.rowcount == 0


def test_app_role_cannot_hard_delete_cases(app_engine, two_tenants):
    """Cases and documents are soft-deleted; the app role has no DELETE grant.

    This is stronger than scoping DELETE by tenant: a hard delete of a case is
    not something the application should be able to do to *anyone*, including
    its own tenant. Deletion goes through deleted_at, which is an UPDATE.
    """
    from sqlalchemy.exc import ProgrammingError

    with app_engine.begin() as conn:
        set_tenant(conn, two_tenants["a"]["tenant"])
        with pytest.raises(ProgrammingError, match="permission denied"):
            conn.execute(
                text("DELETE FROM cases WHERE id = :id"),
                {"id": two_tenants["a"]["case"]},
            )


def test_soft_delete_is_scoped_to_tenant(app_engine, two_tenants):
    """The UPDATE that performs a soft delete must not reach another tenant."""
    with app_engine.begin() as conn:
        set_tenant(conn, two_tenants["a"]["tenant"])
        result = conn.execute(
            text("UPDATE cases SET deleted_at = now() WHERE id = :id"),
            {"id": two_tenants["b"]["case"]},
        )
    assert result.rowcount == 0


def test_insert_with_foreign_tenant_id_is_rejected(app_engine, two_tenants):
    """A tenant must not be able to write rows owned by another tenant.

    Note on WITH CHECK: for a ``FOR ALL`` policy Postgres reuses the USING
    expression as the check on INSERT, so this was already blocked before the
    hardening migration. WITH CHECK is now declared explicitly anyway, because
    that implicit reuse disappears the moment anyone splits the policy into
    per-command policies — a very easy change to make without noticing.
    """
    from sqlalchemy.exc import ProgrammingError

    with app_engine.begin() as conn:
        set_tenant(conn, two_tenants["a"]["tenant"])
        with pytest.raises(ProgrammingError, match="row-level security"):
            conn.execute(
                text(
                    "INSERT INTO cases (tenant_id, case_number, status) "
                    "VALUES (:t, :c, 'intake')"
                ),
                {"t": two_tenants["b"]["tenant"], "c": "smuggled"},
            )


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_table_is_scoped(app_engine, admin_engine, two_tenants, table):
    """Generic: rows of tenant B are invisible from tenant A's context."""
    with app_engine.connect() as conn:
        set_tenant(conn, two_tenants["a"]["tenant"])
        foreign = conn.execute(
            text(f"SELECT count(*) FROM {table} WHERE tenant_id = :t"),
            {"t": two_tenants["b"]["tenant"]},
        ).scalar()
    assert foreign == 0


def test_tenant_context_survives_commit(two_tenants):
    """Regression guard for the SET LOCAL bug.

    ``set_config(..., is_local => true)`` dies with its transaction. The routers
    commit and then refresh, so without re-application the second query runs
    with no tenant at all — invisible rows, or worse, no filtering if RLS is off.
    """
    from app.core.database import SessionLocal
    from app.core.database import set_tenant as apply_tenant
    from app.models.models import Case

    db = SessionLocal()
    try:
        apply_tenant(db, str(two_tenants["a"]["tenant"]))
        assert db.query(Case).count() == 1
        db.commit()
        # New transaction — the tenant must still be in force.
        assert db.query(Case).count() == 1
        current = db.execute(
            text("SELECT current_setting('app.current_tenant_id', true)")
        ).scalar()
        assert current == str(two_tenants["a"]["tenant"])
    finally:
        db.close()
