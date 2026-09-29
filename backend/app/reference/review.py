"""Review-stage product rules: what earns attention, and what blocks submission.

Kept out of the routers on purpose. These are the firm's rules, not HTTP
concerns, and the submission gate has to recompute them server-side (the
readiness endpoint is a convenience, never the enforcement point).
"""

from app.services.referral_email import CASE_TYPE_DEFENCE

# Below this, a value is flagged for a second look. Not a rejection - the real
# extraction run produced plenty of correct values at 0.7 - but the lawyer's
# eye should land there first.
LOW_CONFIDENCE = 0.75

# Bulk-confirm uses the same bar. A separate, stricter number would be two
# thresholds to explain and to keep in step; one is enough until measurement
# says otherwise.
BULK_CONFIRM_MIN_CONFIDENCE = LOW_CONFIDENCE

# Fields that only exist once a pleading has been filed. In a defence case they
# are required; in a claim case the suit has not been filed yet, so empty is the
# correct answer and must never be reported as missing data.
DEFENCE_ONLY_REQUIRED = (
    "court_name",
    "court_city",
    "court_procedure_type",
    "court_case_number",
    "claim_amount",
    "plaintiff_1_name",
)


def required_field_keys(base_required: set[str], case_type: str | None) -> set[str]:
    """The effective required set for one case.

    ``case_fields.is_required`` is the list shared by both case types. The court
    fields carry is_required=False there precisely because a subrogation case
    has none of them; they become required only once the case type says a
    pleading exists.
    """
    if case_type == CASE_TYPE_DEFENCE:
        return base_required | set(DEFENCE_ONLY_REQUIRED)
    return set(base_required)
