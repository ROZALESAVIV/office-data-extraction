import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Float, Boolean, Text, ForeignKey, DateTime
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from database import Base


def _uuid():
    return str(uuid.uuid4())


def _now():
    return datetime.now(timezone.utc)


class Office(Base):
    __tablename__ = "offices"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)

    users = relationship("User", back_populates="office", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="office", cascade="all, delete-orphan")
    cases = relationship("Case", back_populates="office", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    office_id = Column(UUID(as_uuid=False), ForeignKey("offices.id"), nullable=False)
    email = Column(String, unique=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, nullable=False)  # "admin" | "staff"
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)

    office = relationship("Office", back_populates="users")
    documents = relationship("Document", back_populates="uploaded_by_user")
    cases = relationship("Case", back_populates="created_by_user")


class Case(Base):
    __tablename__ = "cases"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    office_id = Column(UUID(as_uuid=False), ForeignKey("offices.id"), nullable=False)
    case_type = Column(String, nullable=False)  # e.g. "car_accident"
    client_name = Column(String, nullable=True)
    otkanit_case_number = Column(String, nullable=True)  # filled after sending to Udukenet
    status = Column(String, nullable=False, default="uploading")
    # status flow: uploading → processing → review → sent | error
    created_by = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)

    office = relationship("Office", back_populates="cases")
    created_by_user = relationship("User", back_populates="cases")
    documents = relationship("Document", back_populates="case", cascade="all, delete-orphan")
    case_fields = relationship("CaseField", back_populates="case", cascade="all, delete-orphan")


class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    office_id = Column(UUID(as_uuid=False), ForeignKey("offices.id"), nullable=False)
    case_id = Column(UUID(as_uuid=False), ForeignKey("cases.id"), nullable=True)
    uploaded_by = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    original_filename = Column(String, nullable=False)
    storage_path = Column(String, nullable=False)
    document_type = Column(String, nullable=True)  # e.g. "insurance", "police_report"
    pdf_type = Column(String, nullable=True)  # "text" | "scanned"
    status = Column(String, nullable=False, default="uploaded")
    # status flow: uploaded → extracting → review → sent | error
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)

    office = relationship("Office", back_populates="documents")
    case = relationship("Case", back_populates="documents")
    uploaded_by_user = relationship("User", back_populates="documents")
    extracted_fields = relationship("ExtractedField", back_populates="document", cascade="all, delete-orphan")
    case_fields = relationship("CaseField", back_populates="source_document")


class ExtractedField(Base):
    __tablename__ = "extracted_fields"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    document_id = Column(UUID(as_uuid=False), ForeignKey("documents.id"), nullable=False)
    field_name = Column(String, nullable=False)
    field_value = Column(String, nullable=True)
    confidence = Column(Float, nullable=False, default=0.0)
    was_corrected = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)

    document = relationship("Document", back_populates="extracted_fields")


class CaseField(Base):
    __tablename__ = "case_fields"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    case_id = Column(UUID(as_uuid=False), ForeignKey("cases.id"), nullable=False)
    field_name = Column(String, nullable=False)
    field_value = Column(String, nullable=True)
    source_document_id = Column(UUID(as_uuid=False), ForeignKey("documents.id"), nullable=True)
    has_conflict = Column(Boolean, nullable=False, default=False)
    conflict_values = Column(Text, nullable=True)  # JSON of all values when has_conflict=true
    was_corrected = Column(Boolean, nullable=False, default=False)
    confidence = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)

    case = relationship("Case", back_populates="case_fields")
    source_document = relationship("Document", back_populates="case_fields")


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    office_id = Column(UUID(as_uuid=False), nullable=False)
    user_id = Column(UUID(as_uuid=False), nullable=False)
    document_id = Column(UUID(as_uuid=False), nullable=True)
    action = Column(String, nullable=False)
    # action values: "uploaded" | "viewed" | "edited" | "sent" | "error"
    details = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)
