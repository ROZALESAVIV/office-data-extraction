"""Review-stage reads: the whole screen in a fixed number of queries, and the
submission readiness rule.

Readiness lives here rather than in the router because the submission endpoint
has to recompute it server-side. A client that skips the readiness call, or
calls it and then races another lawyer, must not be able to submit an
incomplete case.
"""

import uuid
from decimal import Decimal

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.models.models import (
    CaseField,
    CaseFieldValue,
    Document,
    DocumentType,
    FieldCandidate,
)
from app.reference.case_types import CASE_TYPE_DEFENCE, canonical
from app.reference.review import LOW_CONFIDENCE, required_field_keys
from app.schemas.review import (
    Blocker,
    CandidateOut,
    FieldSource,
    ReadinessOut,
    ReviewFieldOut,
    Warning_,
)


def _is_empty(value: str | None) -> bool:
    """Present but blank is not a value: a lawyer's edit can arrive as spaces."""
    return value is None or not value.strip()


def _as_float(value) -> float | None:
    if value is None:
        return None
    return float(value) if isinstance(value, Decimal) else float(value)


def raw_case_type(db: Session, case_id: uuid.UUID) -> str | None:
    """Whatever the case_type field currently holds, recognised or not.

    Read from ``value`` rather than ``extracted_value`` on purpose: if a lawyer
    corrected the type, every downstream rule must follow the correction.
    """
    row = (
        db.query(CaseFieldValue.value)
        .join(CaseField, CaseField.id == CaseFieldValue.field_id)
        .filter(CaseFieldValue.case_id == case_id, CaseField.field_key == "case_type")
        .first()
    )
    if row is None or _is_empty(row[0]):
        return None
    return row[0].strip()


def case_type_of(db: Session, case_id: uuid.UUID) -> str | None:
    """The case type, only if it is one of the two the firm actually has.

    An unrecognised value returns None - "not known" - and readiness turns that
    into a blocker rather than letting it pass as a claim case. Silently
    treating it as a claim would stop requiring the court fields on a defence
    case, which is the direction that loses a filing.
    """
    return canonical(raw_case_type(db, case_id))


def _attention_reasons(
    value: CaseFieldValue | None,
    required_here: bool,
    snippet_verified: bool | None,
) -> list[str]:
    reasons: list[str] = []
    if value is None or _is_empty(value.value):
        if required_here:
            reasons.append("missing_required")
        return reasons
    if value.has_conflict:
        reasons.append("conflict")
    confidence = _as_float(value.confidence_score)
    if confidence is not None and confidence < LOW_CONFIDENCE:
        reasons.append("low_confidence")
    # False means the quote is not on the page the model named. NULL means the
    # page had no text layer to check against, which is the normal state for a
    # scanned file - flagging it would light up almost every field and the flag
    # would stop meaning anything.
    if snippet_verified is False:
        reasons.append("unverified_snippet")
    return reasons


def field_rows(db: Session, case_id: uuid.UUID) -> list[ReviewFieldOut]:
    """Every field in the template, whether or not the case filled it.

    A missing required field has to be *visible* as an empty row; if it were
    simply absent from the response the checklist would look complete.

    Three queries, no N+1: this endpoint is the product, and the difference
    between one join and forty-five lookups is 80ms against three seconds.
    """
    fields = db.query(CaseField).order_by(CaseField.sort_order, CaseField.field_key).all()

    values = {
        v.field_id: v
        for v in db.query(CaseFieldValue).filter(CaseFieldValue.case_id == case_id).all()
    }
    documents = {
        d.id: d
        for d in db.query(Document).filter(Document.case_id == case_id).all()
    }
    counts = dict(
        db.query(FieldCandidate.field_id, func.count(FieldCandidate.id))
        .filter(FieldCandidate.case_id == case_id)
        .group_by(FieldCandidate.field_id)
        .all()
    )
    # Only needed to decide the unverified_snippet flag, and only for the
    # candidate that actually won.
    verified = dict(
        db.query(FieldCandidate.id, FieldCandidate.snippet_verified)
        .filter(FieldCandidate.case_id == case_id)
        .all()
    )

    base_required = {f.field_key for f in fields if f.is_required}
    required_here = required_field_keys(base_required, case_type_of(db, case_id))

    out: list[ReviewFieldOut] = []
    for f in fields:
        v = values.get(f.id)
        is_required_here = f.field_key in required_here
        snippet_verified = verified.get(v.resolved_candidate_id) if v else None
        source = FieldSource()
        if v and v.source_document_id:
            doc = documents.get(v.source_document_id)
            source = FieldSource(
                document_id=v.source_document_id,
                file_name=doc.file_name if doc else None,
                page=v.source_page,
                snippet=v.source_snippet,
            )
        out.append(
            ReviewFieldOut(
                field_id=f.id,
                field_key=f.field_key,
                label=f.label,
                data_type=f.data_type,
                sort_order=f.sort_order,
                is_required=f.is_required,
                required_for_this_case=is_required_here,
                always_needs_review=f.always_needs_review,
                value=v.value if v else None,
                extracted_value=v.extracted_value if v else None,
                status=v.status if v else "pending_review",
                confidence=_as_float(v.confidence_score) if v else None,
                has_conflict=v.has_conflict if v else False,
                conflict_count=v.conflict_count if v else 0,
                conflict_ack_at=v.conflict_ack_at if v else None,
                candidate_count=counts.get(f.id, 0),
                source=source,
                reviewed_by=v.reviewed_by if v else None,
                reviewed_at=v.reviewed_at if v else None,
                updated_at=v.updated_at if v else None,
                attention_reasons=_attention_reasons(v, is_required_here, snippet_verified),
            )
        )
    return out


_CANDIDATES = text("""
    SELECT fc.id, fc.document_id, fc.value, fc.raw_value, fc.confidence, fc.priority,
           fc.source_page, fc.source_snippet, fc.snippet_verified,
           d.file_name, dt.label AS type_label
    FROM field_candidates fc
    JOIN documents d ON d.id = fc.document_id
    LEFT JOIN document_types dt ON dt.id = d.document_type_id
    WHERE fc.case_id = :case_id
      AND fc.field_id = :field_id
      AND d.deleted_at IS NULL
    ORDER BY fc.priority ASC,
             fc.confidence DESC,
             (fc.snippet_verified IS NOT FALSE) DESC,
             d.uploaded_at DESC,
             fc.id ASC
""")


def candidates(db: Session, case_id: uuid.UUID, field_id: uuid.UUID) -> list[CandidateOut]:
    """What each document said about one field, best first.

    The order mirrors the resolver's ranking exactly, so the list the lawyer
    reads is the list the machine ranked - the top row being the current answer
    is then self-evident rather than something they have to take on trust.
    """
    resolved = (
        db.query(CaseFieldValue.resolved_candidate_id)
        .filter(CaseFieldValue.case_id == case_id, CaseFieldValue.field_id == field_id)
        .scalar()
    )
    rows = db.execute(_CANDIDATES, {"case_id": case_id, "field_id": field_id})
    return [
        CandidateOut(
            id=r.id,
            document_id=r.document_id,
            file_name=r.file_name,
            document_type_label=r.type_label,
            value=r.value,
            raw_value=r.raw_value,
            confidence=float(r.confidence),
            priority=r.priority,
            source_page=r.source_page,
            source_snippet=r.source_snippet,
            snippet_verified=r.snippet_verified,
            is_resolved=(r.id == resolved),
        )
        for r in rows
    ]


# ── readiness ────────────────────────────────────────────────────────────────


def readiness(db: Session, case_id: uuid.UUID) -> ReadinessOut:
    """Whether the case may be submitted, and precisely what stands in the way.

    A required field blocks until a lawyer has *decided* on it, not merely until
    it has a value: a machine-extracted value nobody looked at is not a
    confirmed one. 'rejected' blocks too - it means "this is wrong and I have no
    replacement", which is not the same as "not applicable here" (see
    DECISIONS 27).
    """
    fields = {f.id: f for f in db.query(CaseField).all()}
    values = {
        v.field_id: v
        for v in db.query(CaseFieldValue).filter(CaseFieldValue.case_id == case_id).all()
    }
    raw = raw_case_type(db, case_id)
    case_type = canonical(raw)
    base_required = {f.field_key for f in fields.values() if f.is_required}
    required_here = required_field_keys(base_required, case_type)

    blockers: list[Blocker] = []
    warnings: list[Warning_] = []
    confirmed = 0

    for f in sorted(fields.values(), key=lambda x: (x.sort_order, x.field_key)):
        v = values.get(f.id)
        if f.field_key in required_here:
            if v is None or _is_empty(v.value):
                reason = "rejected" if (v is not None and v.status == "rejected") else "missing"
                blockers.append(
                    Blocker(field_id=f.id, field_key=f.field_key, label=f.label, reason=reason)
                )
            elif v.status == "rejected":
                blockers.append(
                    Blocker(field_id=f.id, field_key=f.field_key, label=f.label, reason="rejected")
                )
            elif v.status == "pending_review":
                blockers.append(
                    Blocker(
                        field_id=f.id, field_key=f.field_key, label=f.label, reason="unconfirmed"
                    )
                )
            else:
                confirmed += 1
        elif v is not None and v.has_conflict and v.status == "pending_review":
            # Not blocking: an optional field two documents disagree about is
            # worth a glance, not a locked door.
            warnings.append(
                Warning_(
                    code="unacknowledged_conflict",
                    field_key=f.field_key,
                    detail=f"{v.conflict_count} differing values",
                )
            )

    if case_type is None:
        case_type_field = next(
            (f for f in fields.values() if f.field_key == "case_type"), None
        )
        if raw is not None and case_type_field is not None:
            # A value is there but it is not one of the two types. Left alone it
            # would read as "unknown", and the court fields would quietly stop
            # being required on what may well be a defence case.
            blockers = [b for b in blockers if b.field_key != "case_type"]
            blockers.append(
                Blocker(
                    field_id=case_type_field.id,
                    field_key="case_type",
                    label=case_type_field.label,
                    reason="unrecognised",
                )
            )
        # Without a usable type the court fields cannot be told apart from
        # correctly-empty ones, so the required set above is the cautious, smaller
        # one - and the case cannot be submitted while that is true.
        warnings.append(
            Warning_(
                code="case_type_unknown",
                field_key="case_type",
                detail="Court fields are not being required while the case type is unknown",
            )
        )

    warnings.extend(_deadline_warning(fields, values, case_type))
    warnings.extend(_referral_email_warning(db, case_id))

    return ReadinessOut(
        case_id=case_id,
        case_type=case_type,
        is_ready=not blockers,
        blockers=blockers,
        warnings=warnings,
        confirmed_count=confirmed,
        required_count=len(required_here),
    )


def _deadline_warning(fields, values, case_type) -> list[Warning_]:
    """A defence case with no computed deadline is a warning, never a blocker.

    The rule genuinely cannot produce a date when neither a service stamp nor a
    filing date was found, and refusing to submit the case because of that would
    punish the lawyer for the document's omission. But a defence filing with no
    deadline in sight is exactly the thing to say out loud.
    """
    if case_type != CASE_TYPE_DEFENCE:
        return []
    target = next((f for f in fields.values() if f.field_key == "defence_deadline"), None)
    if target is None:
        return []
    v = values.get(target.id)
    if v is not None and not _is_empty(v.value):
        return []
    return [
        Warning_(
            code="deadline_not_computed",
            field_key="defence_deadline",
            detail="No service date and no court filing date were found",
        )
    ]


def _referral_email_warning(db: Session, case_id: uuid.UUID) -> list[Warning_]:
    """The insurer's email always arrives. If it is not here, someone forgot it.

    Seven of the most reliable fields in the case come out of that one file by
    pattern match. Without it they become guesses, and that is worth saying
    before a lawyer confirms them.
    """
    found = (
        db.query(Document.id)
        .join(DocumentType, DocumentType.id == Document.document_type_id)
        .filter(
            Document.case_id == case_id,
            Document.deleted_at.is_(None),
            DocumentType.type_key == "referral_email",
        )
        .first()
    )
    if found:
        return []
    return [
        Warning_(
            code="referral_email_missing",
            detail="No referral email in this case; seven normally certain fields are inferred",
        )
    ]
