import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func, text
from sqlalchemy.types import TIMESTAMP


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
        CheckConstraint("role IN ('owner','lawyer','staff')", name="ck_users_role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())


class DocumentType(Base):
    __tablename__ = "document_types"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    # False for photographs, licences, cheques: they are uploaded to Odcanit but
    # never sent to the model, which is most of the per-case cost.
    is_extractable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    filename_hints: Mapped[str | None] = mapped_column(Text, nullable=True)


class Sender(Base):
    __tablename__ = "senders"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_senders_tenant_name"),
        Index("idx_senders_tenant_id", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    odcanit_prefix: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())


class Case(Base):
    __tablename__ = "cases"
    __table_args__ = (
        UniqueConstraint("tenant_id", "case_number", name="uq_cases_tenant_case_number"),
        # Target of the composite foreign keys below. Without it a child row
        # could reference a case belonging to a different tenant.
        UniqueConstraint("id", "tenant_id", name="uq_cases_id_tenant"),
        CheckConstraint(
            "status IN ('intake','extracting','ready_for_review','in_review','submitted','closed','failed')",
            name="ck_cases_status",
        ),
        Index("idx_cases_tenant_id", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    case_number: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="intake")
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    sender_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("senders.id"), nullable=True)
    source_email_subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    odcanit_case_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint("file_format IN ('pdf','docx','eml')", name="ck_documents_file_format"),
        CheckConstraint(
            "processing_status IN ('pending','extracting','extracted','partial','skipped','failed')",
            name="ck_documents_processing_status",
        ),
        CheckConstraint(
            "document_type_source IS NULL OR document_type_source IN ('ai','user','filename')",
            name="ck_documents_type_source",
        ),
        Index("idx_documents_case_id", "case_id"),
        Index("idx_documents_tenant_id", "tenant_id"),
        # Same file uploaded twice to one case is one document.
        Index(
            "uq_documents_case_sha", "case_id", "content_sha256", unique=True,
            postgresql_where=text("deleted_at IS NULL AND content_sha256 IS NOT NULL"),
        ),
        # Lets the startup sweeper find documents whose job died mid-run.
        Index(
            "idx_documents_stalled", "processing_status", "processing_started_at",
            postgresql_where=text("processing_status = 'extracting'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    document_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_types.id"), nullable=True
    )
    file_name: Mapped[str] = mapped_column(Text, nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_format: Mapped[str] = mapped_column(Text, nullable=False)
    text_extractable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    processing_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    document_type_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    document_type_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    content_sha256: Mapped[str | None] = mapped_column(Text, nullable=True)
    # PDF rendition for the review viewer; equals storage_path for PDFs.
    preview_storage_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    # Lease held while a background job works on this document, so a crashed
    # job can be told apart from one still running.
    processing_started_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    extraction_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    extraction_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class DocumentTypeField(Base):
    """Which fields to look for in which document type.

    priority is LOWER = MORE authoritative. A field found in the referral email
    (priority 1) beats the same field found in a policy schedule (priority 60).
    """

    __tablename__ = "document_type_fields"
    __table_args__ = (
        CheckConstraint("priority BETWEEN 1 AND 1000", name="ck_dtf_priority"),
        Index("idx_dtf_document_type_id", "document_type_id"),
    )

    document_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_types.id", ondelete="CASCADE"), primary_key=True
    )
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("case_fields.id", ondelete="CASCADE"), primary_key=True
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="100")
    is_required_for_type: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    extraction_hint: Mapped[str | None] = mapped_column(Text, nullable=True)


class FieldCandidate(Base):
    """What one document said about one field.

    case_field_values holds a single answer per field, so without this layer a
    later document silently overwrites an earlier one - precisely the
    disagreement a lawyer needs to see.
    """

    __tablename__ = "field_candidates"
    __table_args__ = (
        UniqueConstraint("document_id", "field_id", name="uq_field_candidates_doc_field"),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1", name="ck_field_candidates_confidence"
        ),
        Index("idx_field_candidates_case_field", "case_id", "field_id"),
        Index("idx_field_candidates_tenant_id", "tenant_id"),
        Index("idx_field_candidates_document_id", "document_id"),
        ForeignKeyConstraint(
            ["case_id", "tenant_id"], ["cases.id", "cases.tenant_id"], name="fk_fc_case_tenant"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    # case_id is part of the composite FK declared in __table_args__ - it must
    # not also carry a plain FK to cases.id.
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    field_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("case_fields.id"), nullable=False
    )
    extraction_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False, server_default="0")
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    # NULL = could not be checked (scanned page, no text layer to compare against)
    snippet_verified: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Denormalised on purpose: re-prioritising config later must not
    # retroactively change the meaning of already-resolved cases.
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class CaseField(Base):
    __tablename__ = "case_fields"
    __table_args__ = (
        CheckConstraint("data_type IN ('text','number','date','boolean')", name="ck_case_fields_data_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    field_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    data_type: Mapped[str] = mapped_column(Text, nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    # Confirmed by a lawyer whatever the confidence. Used for the fields that
    # feed the filing-deadline calculation, where a wrong value is a missed
    # deadline rather than a correctable mistake.
    always_needs_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class CaseFieldValue(Base):
    __tablename__ = "case_field_values"
    __table_args__ = (
        UniqueConstraint("case_id", "field_id", name="uq_case_field_values_case_field"),
        CheckConstraint(
            "status IN ('pending_review','confirmed','edited','rejected')",
            name="ck_case_field_values_status",
        ),
        Index("idx_case_field_values_case_id", "case_id"),
        Index("idx_case_field_values_tenant_id", "tenant_id"),
        ForeignKeyConstraint(
            ["case_id", "tenant_id"], ["cases.id", "cases.tenant_id"], name="fk_cfv_case_tenant"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Part of the composite FK in __table_args__ - no plain FK here.
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    field_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("case_fields.id"), nullable=False)
    extracted_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id"), nullable=True
    )
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending_review")
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    source_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("field_candidates.id", ondelete="SET NULL"), nullable=True
    )
    has_conflict: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    conflict_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    conflict_ack_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)


class OdcanitSubmission(Base):
    __tablename__ = "odcanit_submissions"
    __table_args__ = (
        CheckConstraint("status IN ('pending','success','failed')", name="ck_odcanit_submissions_status"),
        Index("idx_odcanit_submissions_case_id", "case_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    payload_sent: Mapped[dict] = mapped_column(JSONB, nullable=False)
    response_received: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("idx_audit_log_case_id", "case_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    case_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=True)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
