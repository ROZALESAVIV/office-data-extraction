"""always_needs_review

Some fields must be confirmed by a lawyer regardless of how confident the model
is. The filing deadline is computed from the procedure type, the service date
and the claim amount; a wrong deadline is a missed filing, so no confidence
score is high enough to skip a human on those.

Deliberately a column rather than a hard-coded list: the firm expects to relax
this once the extraction has been measured in practice.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'case_fields',
        sa.Column('always_needs_review', sa.Boolean(), nullable=False, server_default='false'),
    )


def downgrade() -> None:
    op.drop_column('case_fields', 'always_needs_review')
