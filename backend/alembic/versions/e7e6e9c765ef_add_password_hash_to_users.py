"""add_password_hash_to_users

Revision ID: e7e6e9c765ef
Revises: 590cb6087bdb
Create Date: 2026-06-20 22:00:28.736940

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7e6e9c765ef'
down_revision: Union[str, Sequence[str], None] = '590cb6087bdb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('password_hash', sa.Text(), nullable=False))


def downgrade() -> None:
    op.drop_column('users', 'password_hash')
