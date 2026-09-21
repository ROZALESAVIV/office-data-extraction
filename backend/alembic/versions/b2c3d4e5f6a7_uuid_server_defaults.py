"""uuid_server_defaults

schema.sql declares ``DEFAULT gen_random_uuid()`` on every primary key, but the
initial migration omitted it on all tables except ``senders``. A migrated
database therefore rejects any INSERT that does not supply an id explicitly.
The application never noticed because the ORM generates ids in Python, but raw
SQL — fixtures, backfills, psql — hits it immediately.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-07

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLES = (
    'tenants',
    'users',
    'document_types',
    'cases',
    'documents',
    'case_fields',
    'case_field_values',
    'odcanit_submissions',
    'audit_log',
)


def upgrade() -> None:
    for table in TABLES:
        op.execute(f'ALTER TABLE {table} ALTER COLUMN id SET DEFAULT gen_random_uuid()')


def downgrade() -> None:
    for table in TABLES:
        op.execute(f'ALTER TABLE {table} ALTER COLUMN id DROP DEFAULT')
