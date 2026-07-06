"""add_senders_and_update_cases

Revision ID: 4f2a7c1d8e93
Revises: e7e6e9c765ef
Create Date: 2026-07-04 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = '4f2a7c1d8e93'
down_revision: Union[str, Sequence[str], None] = 'e7e6e9c765ef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'senders',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', UUID(as_uuid=True), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('odcanit_prefix', sa.Text(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('tenant_id', 'name', name='uq_senders_tenant_name'),
    )
    op.create_index('idx_senders_tenant_id', 'senders', ['tenant_id'])

    op.execute('ALTER TABLE senders ENABLE ROW LEVEL SECURITY')
    op.execute(
        "CREATE POLICY tenant_isolation ON senders "
        "USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )

    op.add_column('cases', sa.Column('sender_id', UUID(as_uuid=True), sa.ForeignKey('senders.id'), nullable=True))
    op.add_column('cases', sa.Column('odcanit_case_number', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('cases', 'odcanit_case_number')
    op.drop_column('cases', 'sender_id')

    op.execute('DROP POLICY IF EXISTS tenant_isolation ON senders')
    op.drop_index('idx_senders_tenant_id', table_name='senders')
    op.drop_table('senders')
