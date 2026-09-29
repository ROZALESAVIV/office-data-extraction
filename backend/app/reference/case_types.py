"""The two case types, and the only spellings that count as either.

The referral email states the instruction verbatim and decides which fields
even exist: a defence case has a pleading already filed in court, a claim
(subrogation) case has not been filed at all, so its court fields are correctly
empty. Every rule that depends on the case type reads it through here.

**Matched exactly, never as a substring.** The same shortcut on the procedure
type turned a fast-track claim into a 60-day one (DECISIONS 22) - silently, and
in the dangerous direction. Here a loose match would be worse still: reading
"להגשת הגנה" as anything other than a recognised value must not quietly turn a
defence case into one with no court fields required.
"""

CASE_TYPE_DEFENCE = "הגנה"
CASE_TYPE_CLAIM = "תביעה"

CASE_TYPES = (CASE_TYPE_DEFENCE, CASE_TYPE_CLAIM)


def canonical(value: str | None) -> str | None:
    """The stored value as one of the two types, or None if it is neither.

    None means *unrecognised*, and callers must treat that as "the case type is
    not known" rather than defaulting to either type. Defaulting to claim would
    stop requiring the court fields on a defence case; defaulting to defence
    would report a subrogation case's correctly-empty fields as missing data.
    """
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped in CASE_TYPES else None
