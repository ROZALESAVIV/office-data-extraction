import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class SenderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    odcanit_prefix: str = Field(min_length=1, max_length=50)


class SenderOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
