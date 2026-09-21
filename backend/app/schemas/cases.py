import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

CaseStatus = Literal[
    "intake", "extracting", "ready_for_review",
    "in_review", "submitted", "closed", "failed",
]


class CaseCreate(BaseModel):
    sender_id: uuid.UUID | None = None
    source_email_subject: str | None = None


class CaseUpdate(BaseModel):
    status: CaseStatus | None = None
    source_email_subject: str | None = None


class CaseOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    case_number: str
    status: str
    created_by: uuid.UUID | None
    sender_id: uuid.UUID | None
    source_email_subject: str | None
    odcanit_case_number: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
