"""Filing deadline for a statement of defence.

Two rules, given by the firm, which are the same rule seen from two sides:

    תאד"מ  (סדר דין מהיר, claims up to  85,000 ILS) -> 45 days from service
    ת.א.   (סדר דין רגיל, claims above 85,000 ILS) -> 60 days from service

The clock starts on the date the claim was SERVED on the defendant - the date
stamped "נתקבל" on the pleading - not the date it was filed or the date we
received the file.

WHAT THIS DELIBERATELY DOES NOT DO
----------------------------------
It does not account for court recess (פגרת בתי המשפט), which can extend a
deadline, nor for any extension granted by the court. A computed date is
therefore an aid, never an authority: it is shown to the lawyer marked as
computed, and the lawyer confirms it like any other field. Missing a filing
deadline is not a defect we are willing to cause, so when anything is uncertain
this returns None and the field is left empty rather than guessed.
"""

from datetime import date, timedelta

FAST_TRACK_DAYS = 45
REGULAR_TRACK_DAYS = 60
# Above this amount a claim goes to the regular track.
FAST_TRACK_AMOUNT_LIMIT = 85_000

# Spellings of each procedure type seen on real pleadings.
_FAST_TRACK_MARKERS = ("תאד\"מ", "תאדמ", "תא\"דמ", "סדר דין מהיר")
_REGULAR_MARKERS = ("ת.א.", "ת\"א", "תא", "סדר דין רגיל")


def days_to_file(procedure_type: str | None, claim_amount: float | None) -> int | None:
    """Days allowed to file a defence, or None when it cannot be determined.

    The procedure type as actually filed wins over the amount: the court has
    already assigned the track, and an unusual amount for that track does not
    change it.
    """
    if procedure_type:
        text = procedure_type.strip()
        if any(m in text for m in _FAST_TRACK_MARKERS):
            return FAST_TRACK_DAYS
        if any(m in text for m in _REGULAR_MARKERS):
            return REGULAR_TRACK_DAYS
    if claim_amount is not None:
        return FAST_TRACK_DAYS if claim_amount <= FAST_TRACK_AMOUNT_LIMIT else REGULAR_TRACK_DAYS
    return None


def defence_deadline(
    service_date: date | None,
    procedure_type: str | None = None,
    claim_amount: float | None = None,
) -> date | None:
    """Computed filing deadline, or None if it cannot be computed safely."""
    if service_date is None:
        return None
    days = days_to_file(procedure_type, claim_amount)
    if days is None:
        return None
    return service_date + timedelta(days=days)
