import uuid
from datetime import datetime

from pydantic import BaseModel


class DocumentOut(BaseModel):
    id: uuid.UUID
    case_id: uuid.UUID
    file_name: str
    file_format: str
    mime_type: str | None
    file_size_bytes: int | None
    page_count: int | None
    text_extractable: bool
    document_type_id: uuid.UUID | None
    document_type_key: str | None = None
    document_type_label: str | None = None
    document_type_source: str | None
    is_extractable: bool | None = None
    processing_status: str
    error_message: str | None
    uploaded_at: datetime
    processed_at: datetime | None
    # True when this file was already in the case and no new row was created.
    duplicate: bool = False

    model_config = {"from_attributes": True}


class DocumentUrlOut(BaseModel):
    url: str
    expires_in_seconds: int


class DocumentTypeOut(BaseModel):
    id: uuid.UUID
    type_key: str
    label: str
    is_extractable: bool

    model_config = {"from_attributes": True}


class DocumentTypeUpdate(BaseModel):
    document_type_id: uuid.UUID
