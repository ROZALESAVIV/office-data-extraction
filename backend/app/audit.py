"""Audit trail helper.

``audit_log`` has existed in the schema, the models and the RLS policies since
the first migration, and nothing has ever written a row to it. Every mutating
endpoint should call :func:`record` so that "who changed this field, and what
did it say before?" is answerable — which for a legal product is not optional.
"""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models.models import AuditLog, User


def record(
    db: Session,
    user: User,
    action: str,
    *,
    case_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Add an audit row to the current transaction. The caller commits."""
    db.add(
        AuditLog(
            tenant_id=user.tenant_id,
            user_id=user.id,
            case_id=case_id,
            action=action,
            details=details,
        )
    )
