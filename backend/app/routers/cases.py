from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app import audit
from app.deps import TenantContext, get_current_user_with_tenant, require_write_role
from app.models.models import Case, Sender
from app.schemas import CaseCreate, CaseOut, CaseUpdate

router = APIRouter(prefix="/cases", tags=["cases"])

# Number of times to retry on a case_number collision. Two tenants racing on
# the same counter is rare; more than a handful of retries means something else
# is wrong and should surface rather than spin.
_MAX_CASE_NUMBER_ATTEMPTS = 5


def _next_case_number(ctx: TenantContext) -> str:
    """Readable per-tenant case number, e.g. ``2026-0007``.

    A lawyer has to say this number out loud on the phone, so it is not a
    truncated UUID. Uniqueness is guaranteed by uq_cases_tenant_case_number;
    this only has to produce a good candidate, and the caller retries.
    """
    year = datetime.now(UTC).year
    prefix = f"{year}-"
    highest = (
        ctx.db.query(func.max(Case.case_number))
        .filter(
            Case.tenant_id == ctx.user.tenant_id,
            Case.case_number.like(f"{prefix}%"),
        )
        .scalar()
    )
    counter = 1
    if highest:
        try:
            counter = int(highest.split("-", 1)[1]) + 1
        except (IndexError, ValueError):
            counter = 1
    return f"{prefix}{counter:04d}"


def _get_case_or_404(ctx: TenantContext, case_id: UUID) -> Case:
    """Load a case scoped to the caller's tenant.

    The tenant_id filter is deliberate defence in depth. RLS should already make
    another tenant's rows invisible; relying on that alone means a single
    misconfigured policy silently exposes every firm's cases.
    """
    case = (
        ctx.db.query(Case)
        .filter(
            Case.id == case_id,
            Case.tenant_id == ctx.user.tenant_id,
            Case.deleted_at.is_(None),
        )
        .first()
    )
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    return case


def _validate_sender(ctx: TenantContext, sender_id: UUID | None) -> UUID | None:
    """Reject a sender belonging to another tenant.

    Postgres evaluates foreign keys as a system operation that bypasses RLS, so
    an unvalidated sender_id from the request body would happily attach another
    firm's sender — and its odcanit_prefix is what gets submitted downstream.
    """
    if sender_id is None:
        return None
    exists = (
        ctx.db.query(Sender.id)
        .filter(Sender.id == sender_id, Sender.tenant_id == ctx.user.tenant_id)
        .first()
    )
    if not exists:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unknown sender",
        )
    return sender_id


@router.post("", response_model=CaseOut, status_code=status.HTTP_201_CREATED)
def create_case(body: CaseCreate, ctx: TenantContext = Depends(require_write_role)):
    sender_id = _validate_sender(ctx, body.sender_id)

    for _ in range(_MAX_CASE_NUMBER_ATTEMPTS):
        case = Case(
            tenant_id=ctx.user.tenant_id,
            case_number=_next_case_number(ctx),
            sender_id=sender_id,
            source_email_subject=body.source_email_subject,
            created_by=ctx.user.id,
            status="intake",
        )
        ctx.db.add(case)
        try:
            ctx.db.flush()
        except IntegrityError:
            ctx.db.rollback()
            continue
        audit.record(
            ctx.db,
            ctx.user,
            "case.created",
            case_id=case.id,
            details={"case_number": case.case_number},
        )
        ctx.db.commit()
        ctx.db.refresh(case)
        return case

    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Could not allocate a case number, please retry",
    )


@router.get("", response_model=list[CaseOut])
def list_cases(ctx: TenantContext = Depends(get_current_user_with_tenant)):
    return (
        ctx.db.query(Case)
        .filter(Case.tenant_id == ctx.user.tenant_id, Case.deleted_at.is_(None))
        .order_by(Case.created_at.desc())
        .all()
    )


@router.get("/{case_id}", response_model=CaseOut)
def get_case(case_id: UUID, ctx: TenantContext = Depends(get_current_user_with_tenant)):
    return _get_case_or_404(ctx, case_id)


@router.patch("/{case_id}", response_model=CaseOut)
def update_case(
    case_id: UUID, body: CaseUpdate, ctx: TenantContext = Depends(require_write_role)
):
    case = _get_case_or_404(ctx, case_id)
    changes: dict[str, object] = {}
    if body.status is not None and body.status != case.status:
        changes["status"] = {"from": case.status, "to": body.status}
        case.status = body.status
    if body.source_email_subject is not None:
        changes["source_email_subject"] = body.source_email_subject
        case.source_email_subject = body.source_email_subject
    case.updated_at = datetime.now(UTC)
    if changes:
        audit.record(ctx.db, ctx.user, "case.updated", case_id=case.id, details=changes)
    ctx.db.commit()
    ctx.db.refresh(case)
    return case


@router.delete("/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_case(case_id: UUID, ctx: TenantContext = Depends(require_write_role)):
    case = _get_case_or_404(ctx, case_id)
    case.deleted_at = datetime.now(UTC)
    audit.record(ctx.db, ctx.user, "case.deleted", case_id=case.id)
    ctx.db.commit()
