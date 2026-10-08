"""The review screen.

A lawyer reads every extracted field, sees where it came from, and decides.
This is the product: everything before it is preparation and everything after
it is transport.

Three rules run through all of it:

* ``extracted_value`` is never named in an update. It is the record of what the
  machine claimed, and the ``trg_freeze_extracted_value`` trigger makes that
  unbypassable - but not naming it means an edit never even tries.
* Every single-field mutation is optimistically locked on ``updated_at``.
* A read never changes the case status; the first *mutation* does.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status

from app import audit
from app.deps import TenantContext, get_current_user_with_tenant, require_write_role
from app.models.models import Case, CaseField, CaseFieldValue, FieldCandidate
from app.reference.case_types import CASE_TYPES, canonical
from app.reference.review import BULK_CONFIRM_MIN_CONFIDENCE
from app.schemas.review import (
    BulkConfirmIn,
    BulkConfirmOut,
    BulkSkip,
    CandidateOut,
    CandidateSelect,
    FieldConfirm,
    FieldEdit,
    FieldReject,
    ReadinessOut,
    ReviewFieldOut,
    ReviewFieldsOut,
)
from app.services import review as review_service

router = APIRouter(prefix="/cases/{case_id}", tags=["review"])

# A finished case is a historical record. Reopening one is a deliberate act,
# not a side effect of someone clicking a field.
FROZEN_CASE_STATUSES = ("submitted", "closed")


def _get_case(ctx: TenantContext, case_id: uuid.UUID) -> Case:
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
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    return case


def _get_mutable_case(ctx: TenantContext, case_id: uuid.UUID) -> Case:
    case = _get_case(ctx, case_id)
    if case.status in FROZEN_CASE_STATUSES:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Case is {case.status}; its fields can no longer be changed"
        )
    return case


def _get_field(ctx: TenantContext, field_id: uuid.UUID) -> CaseField:
    """case_fields is a global template - no tenant column, and read-only here."""
    field = ctx.db.get(CaseField, field_id)
    if field is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Field not found")
    return field


def _load_value(ctx: TenantContext, case_id: uuid.UUID, field_id: uuid.UUID):
    return (
        ctx.db.query(CaseFieldValue)
        .filter(
            CaseFieldValue.case_id == case_id,
            CaseFieldValue.tenant_id == ctx.user.tenant_id,
            CaseFieldValue.field_id == field_id,
        )
        .first()
    )


def _check_lock(row: CaseFieldValue | None, expected: datetime | None) -> None:
    """Refuse a write built on a version of the field somebody has since changed.

    Omitting the token means "I expect no row here yet", which is what a first
    edit of a never-extracted field legitimately expects. It is not a way to opt
    out of the lock: a row that already exists makes that expectation wrong.
    """
    current = row.updated_at if row is not None else None
    if current is None and expected is None:
        return
    if current is None or expected is None or _utc(current) != _utc(expected):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This field changed since you loaded it; reload the case and try again",
        )


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _check_case_type(field: CaseField, value: str) -> None:
    """case_type is a closed choice, not free text.

    Every downstream rule compares it exactly, so a near-miss like "להגשת הגנה"
    would not be read as a defence case: the court fields would stop being
    required and the case would look ready to submit with no court case number.
    Failing the edit here is loud; accepting it fails silently, in the direction
    that loses a filing.
    """
    if field.field_key != "case_type":
        return
    if canonical(value) is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"case_type must be exactly one of: {', '.join(CASE_TYPES)}",
        )


def _begin_review(case: Case) -> None:
    """The first decision, not the first look, puts a case into review.

    'in_review' is terminal in the extraction service's status recomputation, so
    from this moment a newly extracted document no longer moves the case. A
    lawyer glancing at a case must not silently freeze it.
    """
    if case.status == "ready_for_review":
        case.status = "in_review"
    case.updated_at = datetime.now(UTC)


def _mark_reviewed(row: CaseFieldValue, ctx: TenantContext, now: datetime) -> None:
    row.reviewed_by = ctx.user.id
    row.reviewed_at = now
    if row.has_conflict and row.conflict_ack_at is None:
        # Deciding on a field is acknowledging the disagreement in it.
        row.conflict_ack_at = now


def _one(ctx: TenantContext, case_id: uuid.UUID, field_id: uuid.UUID) -> ReviewFieldOut:
    """Rebuild a single row through the same code path as the screen.

    Slightly wasteful, and deliberately so: a second, hand-rolled projection is
    how a mutation's response drifts out of step with the list it came from.
    """
    for row in review_service.field_rows(ctx.db, case_id):
        if row.field_id == field_id:
            return row
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Field not found")


# ── reads ────────────────────────────────────────────────────────────────────


@router.get("/fields", response_model=ReviewFieldsOut)
def list_fields(
    case_id: uuid.UUID, ctx: TenantContext = Depends(get_current_user_with_tenant)
):
    """The whole screen. Staff may read it; only owner/lawyer may decide."""
    case = _get_case(ctx, case_id)
    return ReviewFieldsOut(
        case_id=case.id,
        case_status=case.status,
        case_type=review_service.case_type_of(ctx.db, case.id),
        fields=review_service.field_rows(ctx.db, case.id),
    )


@router.get("/fields/{field_id}/candidates", response_model=list[CandidateOut])
def list_candidates(
    case_id: uuid.UUID,
    field_id: uuid.UUID,
    ctx: TenantContext = Depends(get_current_user_with_tenant),
):
    """What each document said about this field - the conflict, side by side."""
    _get_case(ctx, case_id)
    _get_field(ctx, field_id)
    return review_service.candidates(ctx.db, case_id, field_id)


@router.get("/readiness", response_model=ReadinessOut)
def get_readiness(
    case_id: uuid.UUID, ctx: TenantContext = Depends(get_current_user_with_tenant)
):
    """What still stands between this case and submission.

    A convenience for the screen, never the enforcement point: the submission
    endpoint recomputes exactly this and refuses with the same payload.
    """
    case = _get_case(ctx, case_id)
    return review_service.readiness(ctx.db, case.id)


# ── decisions ────────────────────────────────────────────────────────────────


@router.post("/fields/{field_id}/confirm", response_model=ReviewFieldOut)
def confirm_field(
    case_id: uuid.UUID,
    field_id: uuid.UUID,
    body: FieldConfirm,
    ctx: TenantContext = Depends(require_write_role),
):
    """"What the model said is right." Nothing else changes."""
    case = _get_mutable_case(ctx, case_id)
    field = _get_field(ctx, field_id)
    row = _load_value(ctx, case_id, field_id)
    _check_lock(row, body.expected_updated_at)
    if row is None or row.value is None or not row.value.strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "There is no value to confirm; edit or reject the field instead",
        )

    now = datetime.now(UTC)
    row.status = "confirmed"
    _mark_reviewed(row, ctx, now)
    _begin_review(case)
    audit.record(
        ctx.db, ctx.user, "field.confirmed", case_id=case_id,
        details={"field_key": field.field_key, "value": row.value},
    )
    ctx.db.commit()
    return _one(ctx, case_id, field_id)


@router.patch("/fields/{field_id}", response_model=ReviewFieldOut)
def edit_field(
    case_id: uuid.UUID,
    field_id: uuid.UUID,
    body: FieldEdit,
    ctx: TenantContext = Depends(require_write_role),
):
    """The lawyer's own value.

    Creates the row when nothing was ever extracted - the claim amount in a
    subrogation case is manual entry by design, and a NULL ``extracted_value``
    is the honest record that the model never claimed anything.
    """
    case = _get_mutable_case(ctx, case_id)
    field = _get_field(ctx, field_id)
    row = _load_value(ctx, case_id, field_id)
    _check_lock(row, body.expected_updated_at)

    value = body.value.strip()
    if not value:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "An empty edit is a rejection; use the reject endpoint so the record says so",
        )
    _check_case_type(field, value)

    now = datetime.now(UTC)
    before = row.value if row else None
    if row is None:
        row = CaseFieldValue(
            tenant_id=ctx.user.tenant_id,
            case_id=case_id,
            field_id=field_id,
            extracted_value=None,
            value=value,
            status="edited",
        )
        ctx.db.add(row)
    else:
        # extracted_value is deliberately absent here.
        row.value = value
        row.status = "edited"
    _mark_reviewed(row, ctx, now)
    _begin_review(case)
    audit.record(
        ctx.db, ctx.user, "field.edited", case_id=case_id,
        details={"field_key": field.field_key, "from": before, "to": value},
    )
    ctx.db.commit()
    return _one(ctx, case_id, field_id)


@router.post("/fields/{field_id}/reject", response_model=ReviewFieldOut)
def reject_field(
    case_id: uuid.UUID,
    field_id: uuid.UUID,
    body: FieldReject,
    ctx: TenantContext = Depends(require_write_role),
):
    """"This is wrong and I have no replacement."

    Not "not applicable here" - that case is already covered by the case type,
    which is why a rejected required field still blocks submission. ``value`` is
    cleared; ``extracted_value`` stays as the record of what was claimed.
    """
    case = _get_mutable_case(ctx, case_id)
    field = _get_field(ctx, field_id)
    row = _load_value(ctx, case_id, field_id)
    _check_lock(row, body.expected_updated_at)
    if row is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Nothing was extracted for this field, so there is nothing to reject",
        )

    now = datetime.now(UTC)
    before = row.value
    row.value = None
    row.status = "rejected"
    _mark_reviewed(row, ctx, now)
    _begin_review(case)
    audit.record(
        ctx.db, ctx.user, "field.rejected", case_id=case_id,
        details={"field_key": field.field_key, "was": before},
    )
    ctx.db.commit()
    return _one(ctx, case_id, field_id)


@router.post("/fields/{field_id}/select-candidate", response_model=ReviewFieldOut)
def select_candidate(
    case_id: uuid.UUID,
    field_id: uuid.UUID,
    body: CandidateSelect,
    ctx: TenantContext = Depends(require_write_role),
):
    """How a conflict is actually resolved: believe the other document.

    Retyping the rival value by hand would work and would lose the provenance -
    the answer would read as the lawyer's invention rather than as the registry
    extract it actually is.
    """
    case = _get_mutable_case(ctx, case_id)
    field = _get_field(ctx, field_id)
    candidate = (
        ctx.db.query(FieldCandidate)
        .filter(
            FieldCandidate.id == body.candidate_id,
            FieldCandidate.tenant_id == ctx.user.tenant_id,
            FieldCandidate.case_id == case_id,
            FieldCandidate.field_id == field_id,
        )
        .first()
    )
    if candidate is None:
        # Deliberately not distinguishing "no such candidate" from "belongs to
        # another case": the caller learns nothing either way.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown candidate for this field"
        )
    if candidate.value is None or not candidate.value.strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "That candidate carries no value"
        )
    # The email parser only ever writes a recognised type, but a candidate is
    # still data arriving from outside this endpoint.
    _check_case_type(field, candidate.value)

    row = _load_value(ctx, case_id, field_id)
    _check_lock(row, body.expected_updated_at)

    now = datetime.now(UTC)
    before = row.value if row else None
    if row is None:
        row = CaseFieldValue(
            tenant_id=ctx.user.tenant_id,
            case_id=case_id,
            field_id=field_id,
            extracted_value=None,
            value=candidate.value,
            status="confirmed",
        )
        ctx.db.add(row)
    else:
        row.value = candidate.value
        row.status = "confirmed"
    row.source_document_id = candidate.document_id
    row.source_page = candidate.source_page
    row.source_snippet = candidate.source_snippet
    row.confidence_score = candidate.confidence
    row.resolved_candidate_id = candidate.id
    # Picking a side IS acknowledging the conflict, whichever side was picked.
    row.conflict_ack_at = now
    _mark_reviewed(row, ctx, now)
    _begin_review(case)
    audit.record(
        ctx.db, ctx.user, "field.candidate_selected", case_id=case_id,
        details={
            "field_key": field.field_key,
            "from": before,
            "to": candidate.value,
            "candidate_id": str(candidate.id),
            "document_id": str(candidate.document_id),
        },
    )
    ctx.db.commit()
    return _one(ctx, case_id, field_id)


@router.post("/fields/bulk-confirm", response_model=BulkConfirmOut)
def bulk_confirm(
    case_id: uuid.UUID,
    body: BulkConfirmIn,
    ctx: TenantContext = Depends(require_write_role),
):
    """Clear the uncontroversial fields so the lawyer's attention goes to the rest.

    Never touches a conflicted field, anything marked ``always_needs_review``
    (those feed the filing deadline, where no confidence score is high enough to
    skip a human), or anything already decided. Every field it leaves behind is
    returned with the reason - a silent skip is how a required field gets
    forgotten.

    Not optimistically locked: it only ever acts on fields still in
    ``pending_review``, so a field somebody else has just decided is skipped as
    ``already_reviewed`` rather than overwritten.
    """
    case = _get_mutable_case(ctx, case_id)
    threshold = (
        body.min_confidence if body.min_confidence is not None else BULK_CONFIRM_MIN_CONFIDENCE
    )

    fields = {f.id: f for f in ctx.db.query(CaseField).all()}
    rows = (
        ctx.db.query(CaseFieldValue)
        .filter(
            CaseFieldValue.case_id == case_id,
            CaseFieldValue.tenant_id == ctx.user.tenant_id,
        )
        .all()
    )

    now = datetime.now(UTC)
    confirmed: list[uuid.UUID] = []
    skipped: list[BulkSkip] = []

    for row in sorted(rows, key=lambda r: fields[r.field_id].sort_order):
        field = fields[row.field_id]

        def skip(reason: str, field=field) -> None:
            skipped.append(BulkSkip(field_id=field.id, field_key=field.field_key, reason=reason))

        if row.status != "pending_review" or row.reviewed_at is not None:
            skip("already_reviewed")
        elif row.value is None or not row.value.strip():
            skip("no_value")
        elif row.has_conflict:
            skip("conflict")
        elif field.always_needs_review:
            skip("always_needs_review")
        elif row.confidence_score is None or float(row.confidence_score) < threshold:
            skip("low_confidence")
        else:
            row.status = "confirmed"
            _mark_reviewed(row, ctx, now)
            confirmed.append(field.id)

    if confirmed:
        _begin_review(case)
        audit.record(
            ctx.db, ctx.user, "field.bulk_confirmed", case_id=case_id,
            details={
                "count": len(confirmed),
                "min_confidence": threshold,
                "field_keys": [fields[f].field_key for f in confirmed],
            },
        )
    ctx.db.commit()
    return BulkConfirmOut(confirmed=confirmed, skipped=skipped, min_confidence=threshold)
