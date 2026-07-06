import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func
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
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    sender_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("senders.id"), nullable=True)
    source_email_subject: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    odcanit_case_number: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint("file_format IN ('pdf','docx')", name="ck_documents_file_format"),
        CheckConstraint(
            "processing_status IN ('pending','extracting','extracted','failed')",
            name="ck_documents_processing_status",
        ),
        Index("idx_documents_case_id", "case_id"),
        Index("idx_documents_tenant_id", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    document_type_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("document_types.id"), nullable=True)
    file_name: Mapped[str] = mapped_column(Text, nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_format: Mapped[str] = mapped_column(Text, nullable=False)
    text_extractable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    page_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    processing_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    raw_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extraction_raw: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    uploaded_at: Mapped[str] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    processed_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True)


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
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    field_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("case_fields.id"), nullable=False)
    extracted_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_document_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=True)
    source_page: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    confidence_score: Mapped[Optional[float]] = mapped_column(Numeric(4, 3), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending_review")
    reviewed_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())


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
    response_received: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    submitted_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("idx_audit_log_case_id", "case_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    case_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=True)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
