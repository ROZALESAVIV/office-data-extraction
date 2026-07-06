import uuid as _uuid
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.deps import get_current_user_with_tenant
from app.schemas import CaseCreate, CaseOut, CaseUpdate
from models.models import Case

router = APIRouter(prefix="/cases", tags=["cases"])


@router.post("", response_model=CaseOut, status_code=status.HTTP_201_CREATED)
def create_case(body: CaseCreate, ctx=Depends(get_current_user_with_tenant)):
    db, user = ctx
    case = Case(
        tenant_id=user.tenant_id,
        case_number=str(_uuid.uuid4())[:8],
        sender_id=body.sender_id,
        source_email_subject=body.source_email_subject,
        created_by=user.id,
        status="intake",
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


@router.get("", response_model=list[CaseOut])
def list_cases(ctx=Depends(get_current_user_with_tenant)):
    db, user = ctx
    return (
        db.query(Case)
        .filter(Case.deleted_at.is_(None))
        .order_by(Case.created_at.desc())
        .all()
    )


@router.get("/{case_id}", response_model=CaseOut)
def get_case(case_id: UUID, ctx=Depends(get_current_user_with_tenant)):
    db, user = ctx
    case = db.query(Case).filter(Case.id == case_id, Case.deleted_at.is_(None)).first()
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    return case


@router.patch("/{case_id}", response_model=CaseOut)
def update_case(case_id: UUID, body: CaseUpdate, ctx=Depends(get_current_user_with_tenant)):
    db, user = ctx
    case = db.query(Case).filter(Case.id == case_id, Case.deleted_at.is_(None)).first()
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    if body.status is not None:
        case.status = body.status
    if body.source_email_subject is not None:
        case.source_email_subject = body.source_email_subject
    case.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(case)
    return case


@router.delete("/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_case(case_id: UUID, ctx=Depends(get_current_user_with_tenant)):
    db, user = ctx
    case = db.query(Case).filter(Case.id == case_id, Case.deleted_at.is_(None)).first()
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    case.deleted_at = datetime.now(timezone.utc)
    db.commit()
