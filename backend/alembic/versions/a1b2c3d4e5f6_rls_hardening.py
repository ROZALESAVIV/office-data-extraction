"""rls_hardening

Make tenant isolation actually enforced.

Three separate defects made the previous policies inert:

1. The application connected as Supabase's default ``postgres`` role, which is
   both the table owner and a SUPERUSER. Postgres skips RLS policies entirely
   for such a role, so the policies existed but were never evaluated. The real
   fix is the dedicated ``app_db_role`` created below; ``FORCE ROW LEVEL
   SECURITY`` only closes the plain-owner case and does nothing against a
   superuser or a BYPASSRLS role.
2. No ``WITH CHECK``. For a ``FOR ALL`` policy Postgres reuses ``USING`` as the
   insert check, so this was not exploitable on its own — but that implicit
   reuse disappears if the policy is ever split per command, so it is now
   declared explicitly.
3. No composite foreign key, so a case_field_values row could reference a case
   belonging to a different tenant.

Revision ID: a1b2c3d4e5f6
Revises: 4f2a7c1d8e93
Create Date: 2026-09-07

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op
from app.core.config import settings

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '4f2a7c1d8e93'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TENANT_TABLES = (
    'senders',
    'cases',
    'documents',
    'case_field_values',
    'odcanit_submissions',
    'audit_log',
)

# Global template tables. The application reads them but must never write them;
# changing them is a migration/admin concern.
READ_ONLY_TABLES = ('document_types', 'case_fields', 'tenants')


def upgrade() -> None:
    for table in TENANT_TABLES:
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON {table}')
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
                USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
                WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
        """)
        op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')

    # A value row must belong to the same tenant as its case. Without this, RLS
    # on case_field_values could be satisfied while pointing at a foreign case.
    op.create_unique_constraint('uq_cases_id_tenant', 'cases', ['id', 'tenant_id'])
    op.create_foreign_key(
        'fk_cfv_case_tenant',
        'case_field_values',
        'cases',
        ['case_id', 'tenant_id'],
        ['id', 'tenant_id'],
    )

    _create_app_role()


def _create_app_role() -> None:
    role = settings.app_db_role
    password = settings.app_db_password
    if not role:
        print(
            'rls_hardening: app_db_role not configured — policies hardened, but '
            'the application role was NOT created. Tenant isolation is only '
            'enforced if the app connects as a non-owner role without BYPASSRLS.'
        )
        return

    conn = op.get_bind()
    exists = conn.execute(
        sa.text('SELECT 1 FROM pg_roles WHERE rolname = :r'), {'r': role}
    ).scalar()

    ident = f'"{role}"'
    if not exists:
        if not password:
            raise RuntimeError('app_db_role is set but app_db_password is empty')
        conn.execute(
            sa.text(f'CREATE ROLE {ident} LOGIN PASSWORD :pw '
                    'NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE'),
            {'pw': password},
        )
    else:
        # Enforce the safety attributes even on a pre-existing role.
        conn.execute(sa.text(f'ALTER ROLE {ident} NOSUPERUSER NOBYPASSRLS'))
        if password:
            conn.execute(sa.text(f'ALTER ROLE {ident} PASSWORD :pw'), {'pw': password})

    op.execute(f'GRANT USAGE ON SCHEMA public TO {ident}')
    op.execute(f'GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO {ident}')
    op.execute(f'GRANT SELECT, USAGE ON ALL SEQUENCES IN SCHEMA public TO {ident}')
    for table in READ_ONLY_TABLES:
        op.execute(f'REVOKE INSERT, UPDATE, DELETE ON {table} FROM {ident}')


def downgrade() -> None:
    op.drop_constraint('fk_cfv_case_tenant', 'case_field_values', type_='foreignkey')
    op.drop_constraint('uq_cases_id_tenant', 'cases', type_='unique')

    for table in TENANT_TABLES:
        op.execute(f'ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY')
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON {table}')
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
                USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
        """)
