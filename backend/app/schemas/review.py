import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

FieldStatus = Literal["pending_review", "confirmed", "edited", "rejected"]

# Why the review screen should draw the lawyer's eye to a field. Deliberately a
# closed set: an open-ended list of hints degrades into noise nobody reads.
AttentionReason = Literal[
    "conflict",
    "low_confidence",
    "unverified_snippet",
    "missing_required",
    # A plate equalling an ID number in the same case - confirmed by the firm,
    # 2026-09-29. Real example: a plate field returned the insured's own ID
    # missing its leading zero.
    "plate_matches_id",
    # Total paid = 0 - confirmed always worth a second look: "necessarily a
    # mistake" in a claim case, "a sign of an error" in a defence case.
    "suspicious_zero",
]


class FieldSource(BaseModel):
    """Where the current value came from - what drives the jump into the viewer."""

    document_id: uuid.UUID | None = None
    file_name: str | None = None
    page: int | None = None
    snippet: str | None = None


class ReviewFieldOut(BaseModel):
    field_id: uuid.UUID
    field_key: str
    label: str
    data_type: str
    sort_order: int
    # is_required is the global template flag; required_for_this_case applies
    # the case type on top of it, and is the one the submission gate uses.
    is_required: bool
    required_for_this_case: bool
    always_needs_review: bool

    value: str | None = None
    extracted_value: str | None = None
    status: FieldStatus = "pending_review"
    confidence: float | None = None
    has_conflict: bool = False
    conflict_count: int = 0
    conflict_ack_at: datetime | None = None
    candidate_count: int = 0
    source: FieldSource = Field(default_factory=FieldSource)
    reviewed_by: uuid.UUID | None = None
    reviewed_at: datetime | None = None
    # The optimistic-locking token. None when no row exists yet, which is
    # itself the expected value a first edit must send back.
    updated_at: datetime | None = None
    attention_reasons: list[AttentionReason] = Field(default_factory=list)


class ReviewFieldsOut(BaseModel):
    case_id: uuid.UUID
    case_status: str
    case_type: str | None = None
    fields: list[ReviewFieldOut]


class CandidateOut(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    file_name: str
    document_type_label: str | None = None
    value: str | None = None
    raw_value: str | None = None
    confidence: float
    priority: int
    source_page: int | None = None
    source_snippet: str | None = None
    # None means the page carried no text layer to check against, not that the
    # quote was wrong.
    snippet_verified: bool | None = None
    is_resolved: bool = False


class _Locked(BaseModel):
    """Optimistic lock. Omit it only when you expect no row to exist yet."""

    expected_updated_at: datetime | None = None


class FieldConfirm(_Locked):
    pass


class FieldEdit(_Locked):
    value: str


class FieldReject(_Locked):
    """No reason field - confirmed with the firm (2026-09-29): the workflow is
    either type the correct value, or clear it and leave it blank until someone
    knows the answer. No separate written explanation is part of that."""


class CandidateSelect(_Locked):
    candidate_id: uuid.UUID


class BulkConfirmIn(BaseModel):
    min_confidence: float | None = Field(default=None, ge=0, le=1)


class BulkSkip(BaseModel):
    field_id: uuid.UUID
    field_key: str
    # Never skip silently: every field left behind says why.
    reason: Literal[
        "no_value",
        "already_reviewed",
        "conflict",
        "always_needs_review",
        "low_confidence",
    ]


class BulkConfirmOut(BaseModel):
    confirmed: list[uuid.UUID]
    skipped: list[BulkSkip]
    min_confidence: float


class Blocker(BaseModel):
    field_id: uuid.UUID
    field_key: str
    label: str
    # 'unrecognised' is only ever case_type holding something that is neither
    # of the two types - which must block rather than read as "unknown".
    reason: Literal["missing", "unconfirmed", "rejected", "unrecognised"]


class Warning_(BaseModel):
    code: Literal[
        "case_type_unknown",
        "unacknowledged_conflict",
        "deadline_not_computed",
        "referral_email_missing",
    ]
    field_key: str | None = None
    detail: str | None = None


class ReadinessOut(BaseModel):
    case_id: uuid.UUID
    case_type: str | None = None
    is_ready: bool
    blockers: list[Blocker]
    warnings: list[Warning_]
    confirmed_count: int
    required_count: int
