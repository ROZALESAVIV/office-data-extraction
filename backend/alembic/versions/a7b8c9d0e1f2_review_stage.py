"""review_stage

The review API needs ``case_field_values.updated_at`` to be a trustworthy
optimistic-locking token: two lawyers in one case on a Monday morning is a real
scenario, and last-write-wins would silently discard one of their decisions.

The column already existed but only carried a ``server_default``, so it was
accurate exactly as long as every current and future router remembered to set
it by hand. That is the same class of mistake DECISIONS 7 moved into a trigger,
for the same reason: a lock that depends on developer discipline is not a lock.

``clock_timestamp()`` rather than ``now()`` - ``now()`` is the transaction start
time, so two updates to one row inside a single transaction would leave the
token unchanged and a stale one would be accepted.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-09-24

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, Sequence[str], None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION touch_case_field_value() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            NEW.updated_at := clock_timestamp();
            RETURN NEW;
        END $$;
    """)
    # Fires after trg_freeze_extracted_value: triggers on one table run in name
    # order, and 'trg_freeze...' sorts before 'trg_touch...'. A rejected update
    # must not get a fresh timestamp on its way to being aborted anyway.
    op.execute("""
        CREATE TRIGGER trg_touch_case_field_value BEFORE UPDATE ON case_field_values
            FOR EACH ROW EXECUTE FUNCTION touch_case_field_value();
    """)


def downgrade() -> None:
    op.execute('DROP TRIGGER IF EXISTS trg_touch_case_field_value ON case_field_values')
    op.execute('DROP FUNCTION IF EXISTS touch_case_field_value()')
