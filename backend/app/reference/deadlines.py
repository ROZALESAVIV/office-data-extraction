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

from dataclasses import dataclass
from datetime import date, timedelta

FAST_TRACK_DAYS = 45
REGULAR_TRACK_DAYS = 60
# Above this amount a claim goes to the regular track.
FAST_TRACK_AMOUNT_LIMIT = 85_000

# Procedure types are written many ways: תא"מ, תאד"מ, ת.א., ת"א. Matching on
# substrings is unsafe - "תא" is contained in "תא\"מ", which silently turns a
# 45-day fast-track deadline into a 60-day one. Fifteen days a lawyer does not
# actually have is the dangerous direction to be wrong in.
#
# So strip the punctuation that varies and compare whole words instead.
_PUNCT = str.maketrans("", "", '"\'״׳.,-־ \t')

# Normalised forms, not substrings.
_FAST_TRACK_FORMS = {"תאמ", "תאדמ", "תדמ"}
_REGULAR_FORMS = {"תא"}
# Phrases that name the track outright; these are safe to search for.
_FAST_TRACK_PHRASES = ("סדר דין מהיר", "סד\"מ")
_REGULAR_PHRASES = ("סדר דין רגיל",)


def _normalise_procedure(text: str) -> str:
    return text.translate(_PUNCT)


def days_to_file(procedure_type: str | None, claim_amount: float | None) -> int | None:
    """Days allowed to file a defence, or None when it cannot be determined.

    The procedure type as actually filed wins over the amount: the court has
    already assigned the track, and an unusual amount for that track does not
    change it.
    """
    if procedure_type:
        text = procedure_type.strip()
        if any(p in text for p in _FAST_TRACK_PHRASES):
            return FAST_TRACK_DAYS
        if any(p in text for p in _REGULAR_PHRASES):
            return REGULAR_TRACK_DAYS
        # Compare the first token, stripped of punctuation, as a whole word.
        head = _normalise_procedure(text.split()[0]) if text.split() else ""
        if head in _FAST_TRACK_FORMS:
            return FAST_TRACK_DAYS
        if head in _REGULAR_FORMS:
            return REGULAR_TRACK_DAYS
    if claim_amount is not None:
        return FAST_TRACK_DAYS if claim_amount <= FAST_TRACK_AMOUNT_LIMIT else REGULAR_TRACK_DAYS
    return None


@dataclass(frozen=True)
class Deadline:
    date: date
    # Which date the clock was started from, and where the day count came from.
    counted_from: str  # "service" | "filing"
    days: int
    days_source: str  # "summons" | "procedure_type" | "claim_amount"

    @property
    def is_cautious(self) -> bool:
        """True when no service date existed and filing was used instead.

        The firm treats this as the safe assumption, but it is an assumption -
        the real clock starts later, so this date is earlier than the true one.
        """
        return self.counted_from == "filing"


def defence_deadline(
    service_date: date | None,
    procedure_type: str | None = None,
    claim_amount: float | None = None,
    stated_days: int | None = None,
    filing_date: date | None = None,
) -> Deadline | None:
    """Computed filing deadline, or None if it cannot be computed safely.

    Order of preference, as set by the firm:

    1. Service date + the day count stated in the summons.
    2. Service date + the day count derived from the procedure type or amount.
    3. No service date (the stamp is often simply absent): count from the
       court's filing date instead. That is earlier than the true deadline,
       which is the direction of caution.
    4. Nothing usable: return None. Never guess a date a lawyer might rely on.
    """
    days, source = None, None
    if stated_days and stated_days > 0:
        days, source = int(stated_days), "summons"
    else:
        derived = days_to_file(procedure_type, claim_amount)
        if derived is not None:
            days = derived
            source = "procedure_type" if procedure_type else "claim_amount"
    if days is None:
        return None

    if service_date is not None:
        return Deadline(service_date + timedelta(days=days), "service", days, source)
    if filing_date is not None:
        return Deadline(filing_date + timedelta(days=days), "filing", days, source)
    return None
