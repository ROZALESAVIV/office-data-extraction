import uuid

from pydantic import BaseModel


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
