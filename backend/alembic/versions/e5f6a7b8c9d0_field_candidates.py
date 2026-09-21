"""field_candidates

One row per (document, field): what each document said about each field, with
its confidence, page and a verbatim quote.

Why this exists: several documents in a case answer the same question, sometimes
differently. `case_field_values` holds one answer per field, so without this
layer a later document silently overwrites an earlier one — which is exactly the
disagreement a lawyer must see rather than have hidden.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op
from app.core.config import settings

revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'field_candidates',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('case_id', sa.UUID(), nullable=False),
        sa.Column('document_id', sa.UUID(), nullable=False),
        sa.Column('field_id', sa.UUID(), nullable=False),
        sa.Column('extraction_run_id', sa.UUID(), nullable=False),
        # value is normalised per case_fields.data_type; raw_value is exactly
        # what the source produced, kept for debugging prompts.
        sa.Column('value', sa.Text()),
        sa.Column('raw_value', sa.Text()),
        sa.Column('confidence', sa.Numeric(4, 3), nullable=False, server_default='0'),
        sa.Column('source_page', sa.Integer()),
        sa.Column('source_snippet', sa.Text()),
        # NULL = could not be checked (scanned page, no text layer).
        sa.Column('snippet_verified', sa.Boolean()),
        # Denormalised from document_type_fields deliberately: re-prioritising
        # config later must not retroactively change already-resolved cases.
        sa.Column('priority', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['case_id', 'tenant_id'], ['cases.id', 'cases.tenant_id']),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['field_id'], ['case_fields.id']),
        # The idempotency backbone: re-running extraction is delete-by-document
        # plus insert, in one transaction.
        sa.UniqueConstraint('document_id', 'field_id', name='uq_field_candidates_doc_field'),
        sa.CheckConstraint('confidence >= 0 AND confidence <= 1',
                           name='ck_field_candidates_confidence'),
    )
    op.create_index('idx_field_candidates_case_field', 'field_candidates', ['case_id', 'field_id'])
    op.create_index('idx_field_candidates_tenant_id', 'field_candidates', ['tenant_id'])
    op.create_index('idx_field_candidates_document_id', 'field_candidates', ['document_id'])

    op.execute('ALTER TABLE field_candidates ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE field_candidates FORCE ROW LEVEL SECURITY')
    op.execute("""
        CREATE POLICY tenant_isolation ON field_candidates
            USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    """)

    op.add_column('case_field_values', sa.Column('source_snippet', sa.Text()))
    op.add_column('case_field_values', sa.Column('resolved_candidate_id', sa.UUID()))
    op.add_column('case_field_values',
                  sa.Column('has_conflict', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('case_field_values',
                  sa.Column('conflict_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('case_field_values', sa.Column('conflict_ack_at', sa.TIMESTAMP(timezone=True)))
    op.add_column('case_field_values', sa.Column('resolved_at', sa.TIMESTAMP(timezone=True)))
    op.create_foreign_key(
        'fk_cfv_resolved_candidate', 'case_field_values', 'field_candidates',
        ['resolved_candidate_id'], ['id'], ondelete='SET NULL',
    )

    # extracted_value stays correctable while nobody has looked at the field, so
    # a better source document arriving later can still fix it. The moment a
    # lawyer confirms, edits or rejects, it is frozen for good. Enforced here
    # rather than in a router so a future careless endpoint cannot bypass it.
    op.execute("""
        CREATE FUNCTION freeze_extracted_value() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.extracted_value IS DISTINCT FROM NEW.extracted_value
               AND (OLD.status <> 'pending_review' OR OLD.reviewed_at IS NOT NULL) THEN
                RAISE EXCEPTION
                    'extracted_value is frozen once the field has been reviewed (field %)',
                    OLD.field_id
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END $$;
    """)
    op.execute("""
        CREATE TRIGGER trg_freeze_extracted_value BEFORE UPDATE ON case_field_values
            FOR EACH ROW EXECUTE FUNCTION freeze_extracted_value();
    """)

    # Redundant now: fk_cfv_case_tenant (added in rls_hardening) checks the
    # same reference AND that the tenant matches. Leaving both would make
    # `alembic --autogenerate` propose dropping one of them at random.
    op.drop_constraint('case_field_values_case_id_fkey', 'case_field_values', type_='foreignkey')

    role = settings.app_db_role
    if role:
        # DELETE is granted only here: candidates are derived data that the
        # extraction job rewrites wholesale. No other table allows it.
        op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON field_candidates TO "{role}"')


def downgrade() -> None:
    op.create_foreign_key(
        'case_field_values_case_id_fkey', 'case_field_values', 'cases', ['case_id'], ['id']
    )
    op.execute('DROP TRIGGER IF EXISTS trg_freeze_extracted_value ON case_field_values')
    op.execute('DROP FUNCTION IF EXISTS freeze_extracted_value()')
    op.drop_constraint('fk_cfv_resolved_candidate', 'case_field_values', type_='foreignkey')
    for col in ('resolved_at', 'conflict_ack_at', 'conflict_count', 'has_conflict',
                'resolved_candidate_id', 'source_snippet'):
        op.drop_column('case_field_values', col)
    op.drop_table('field_candidates')
