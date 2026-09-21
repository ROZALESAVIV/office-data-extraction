"""extraction_mapping

Which fields to look for in which document type, and which document types are
worth sending to the model at all.

Most documents in a motor-claim file are photographs — damage shots, licences,
cheques, police forms. They carry no extractable field data but still have to be
uploaded to Odcanit. ``document_types.is_extractable`` is what keeps them out of
the extraction pipeline, which is the difference between roughly $2.50 and $1.00
per case.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op
from app.core.config import settings

revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'document_types',
        sa.Column('is_extractable', sa.Boolean(), nullable=False, server_default='true'),
    )
    op.add_column('document_types', sa.Column('description', sa.Text(), nullable=True))
    # Filename patterns the classifier can use as a prior. Not authoritative —
    # the model still decides — but a strong hint and free.
    op.add_column('document_types', sa.Column('filename_hints', sa.Text(), nullable=True))

    op.create_table(
        'document_type_fields',
        sa.Column('document_type_id', sa.UUID(), nullable=False),
        sa.Column('field_id', sa.UUID(), nullable=False),
        # LOWER priority = MORE authoritative. 1 beats 100.
        sa.Column('priority', sa.Integer(), nullable=False, server_default='100'),
        sa.Column('is_required_for_type', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('extraction_hint', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['document_type_id'], ['document_types.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['field_id'], ['case_fields.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('document_type_id', 'field_id'),
        sa.CheckConstraint('priority BETWEEN 1 AND 1000', name='ck_dtf_priority'),
    )
    op.create_index('idx_dtf_document_type_id', 'document_type_fields', ['document_type_id'])

    # This table is global configuration: the app reads it, migrations write it.
    role = settings.app_db_role
    if role:
        op.execute(f'GRANT SELECT ON document_type_fields TO "{role}"')


def downgrade() -> None:
    op.drop_index('idx_dtf_document_type_id', table_name='document_type_fields')
    op.drop_table('document_type_fields')
    op.drop_column('document_types', 'filename_hints')
    op.drop_column('document_types', 'description')
    op.drop_column('document_types', 'is_extractable')
