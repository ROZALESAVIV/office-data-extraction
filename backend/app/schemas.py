import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel

# ── Auth ──────────────────────────────────────────────────────────────────────

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: str
    tenant_id: uuid.UUID

    model_config = {"from_attributes": True}


# ── Cases ─────────────────────────────────────────────────────────────────────

CaseStatus = Literal[
    "intake", "extracting", "ready_for_review",
    "in_review", "submitted", "closed", "failed"
]


class CaseCreate(BaseModel):
    sender_id: Optional[uuid.UUID] = None
    source_email_subject: Optional[str] = None


class CaseUpdate(BaseModel):
    status: Optional[CaseStatus] = None
    source_email_subject: Optional[str] = None


class CaseOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    case_number: str
    status: str
    created_by: Optional[uuid.UUID]
    sender_id: Optional[uuid.UUID]
    source_email_subject: Optional[str]
    odcanit_case_number: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Senders ───────────────────────────────────────────────────────────────────

class SenderCreate(BaseModel):
    name: str
    odcanit_prefix: str


class SenderOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
