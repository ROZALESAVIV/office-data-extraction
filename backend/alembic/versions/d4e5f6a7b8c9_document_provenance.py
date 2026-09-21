"""document_provenance

Columns the extraction pipeline needs on `documents`: what the classifier
decided, a lease so a crashed job can be recovered, and a content hash so the
same file uploaded twice does not become two documents.

Also widens file_format to accept 'eml'. The referral email from the insurer is
the single most reliable source in the whole case file — six fields in a fixed
template, no OCR, no ambiguity — so it is modelled as just another document and
flows through the same candidate/resolution machinery.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('documents', sa.Column('document_type_confidence', sa.Numeric(4, 3)))
    op.add_column('documents', sa.Column('document_type_source', sa.Text()))
    op.add_column('documents', sa.Column('mime_type', sa.Text()))
    op.add_column('documents', sa.Column('file_size_bytes', sa.BigInteger()))
    op.add_column('documents', sa.Column('content_sha256', sa.Text()))
    # PDF rendition used by the review viewer. Equals storage_path for PDFs;
    # for DOCX it is the converted copy.
    op.add_column('documents', sa.Column('preview_storage_path', sa.Text()))
    op.add_column('documents', sa.Column('uploaded_by', sa.UUID()))
    op.add_column('documents', sa.Column('processing_started_at', sa.TIMESTAMP(timezone=True)))
    op.add_column(
        'documents',
        sa.Column('extraction_attempts', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column('documents', sa.Column('extraction_run_id', sa.UUID()))

    op.create_foreign_key(
        'fk_documents_uploaded_by', 'documents', 'users', ['uploaded_by'], ['id']
    )
    op.create_check_constraint(
        'ck_documents_type_source',
        'documents',
        "document_type_source IS NULL OR document_type_source IN ('ai','user','filename')",
    )

    op.drop_constraint('ck_documents_file_format', 'documents', type_='check')
    op.create_check_constraint(
        'ck_documents_file_format', 'documents', "file_format IN ('pdf','docx','eml')"
    )

    # 'partial' — some page windows succeeded and some failed. Without it, a
    # document that yielded half its fields is indistinguishable from a total
    # failure.
    op.drop_constraint('ck_documents_processing_status', 'documents', type_='check')
    op.create_check_constraint(
        'ck_documents_processing_status',
        'documents',
        "processing_status IN ('pending','extracting','extracted','partial','skipped','failed')",
    )

    op.execute(
        'CREATE UNIQUE INDEX uq_documents_case_sha ON documents(case_id, content_sha256) '
        'WHERE deleted_at IS NULL AND content_sha256 IS NOT NULL'
    )
    op.execute(
        'CREATE INDEX idx_documents_stalled ON documents(processing_status, processing_started_at) '
        "WHERE processing_status = 'extracting'"
    )


def downgrade() -> None:
    op.execute('DROP INDEX IF EXISTS idx_documents_stalled')
    op.execute('DROP INDEX IF EXISTS uq_documents_case_sha')
    op.drop_constraint('ck_documents_processing_status', 'documents', type_='check')
    op.create_check_constraint(
        'ck_documents_processing_status',
        'documents',
        "processing_status IN ('pending','extracting','extracted','failed')",
    )
    op.drop_constraint('ck_documents_file_format', 'documents', type_='check')
    op.create_check_constraint(
        'ck_documents_file_format', 'documents', "file_format IN ('pdf','docx')"
    )
    op.drop_constraint('ck_documents_type_source', 'documents', type_='check')
    op.drop_constraint('fk_documents_uploaded_by', 'documents', type_='foreignkey')
    for col in ('extraction_run_id', 'extraction_attempts', 'processing_started_at',
                'uploaded_by', 'preview_storage_path', 'content_sha256',
                'file_size_bytes', 'mime_type', 'document_type_source',
                'document_type_confidence'):
        op.drop_column('documents', col)
