"""Parse the insurer's referral email.

This is the highest-value source in a case file and the only one that needs no
model at all. Direct Insurance sends a fixed template, so seven fields come out
by pattern match: exact, free, and with no possibility of an OCR error.

Everything returned here is given confidence 1.0 and the top priority in
document_type_fields, so nothing else can outrank it.

If the template ever changes, the patterns stop matching and the fields come
back empty rather than wrong - which the review screen shows as missing. That
is the correct failure: silence, not a plausible-looking wrong answer.
"""

import email
import html
import re
from dataclasses import dataclass, field
from email import policy

from app.services.files import normalize_date, normalize_he

# What the firm is being asked to do. Stated verbatim in the email, and it
# decides which fields are even applicable: a defence case has a pleading to
# read, a claim case has not been filed yet.
CASE_TYPE_DEFENCE = "הגנה"
CASE_TYPE_CLAIM = "תביעה"

_PATTERNS = {
    "direct_claim_number": r"מספר\s+תביעה\s*:\s*(\S+)",
    "direct_policy_number": r"מספר\s+פוליסה\s*:\s*(\S+)",
    "insured_plate_number": r"מספר\s+רישוי\s*:\s*(\d+)",
    "accident_date": r"תאריך\s+אירוע\s*:\s*([\d./-]+)",
    "insured_name": r"שם\s+מבוטחנו\s*:\s*(.+?)\s*(?:\.|,)?\s*שם\s+צד\s+ג",
    "third_party_insurer": r"שם\s+צד\s+ג'?\s*:\s*(.+?)\s*שם\s+המטפל",
}
_CASE_TYPE_PATTERN = r"התיק\s+מועבר\s+לטיפולך\s+להגשת\s+(\S+)"
_HANDLER_PATTERN = r"שם\s+המטפל\s+המשויך\s+לתביעה\s*:\s*(.+?)\s{2,}|שם\s+המטפל\s+המשויך\s+לתביעה\s*:\s*(\S+\s+\S+)"


@dataclass
class ReferralEmail:
    subject: str | None = None
    sender: str | None = None
    sent_at: str | None = None
    fields: dict[str, str] = field(default_factory=dict)
    body: str = ""

    @property
    def case_type(self) -> str | None:
        return self.fields.get("case_type")


def _plain_text(message) -> str:
    part = message.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    text = part.get_content()
    if part.get_content_type() == "text/html":
        text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    return " ".join(text.split())


def parse(blob: bytes) -> ReferralEmail:
    """Extract what the referral email states outright."""
    message = email.message_from_bytes(blob, policy=policy.default)
    text = _plain_text(message)
    result = ReferralEmail(
        subject=message.get("Subject"),
        sender=message.get("From"),
        sent_at=message.get("Date"),
        body=text,
    )

    for key, pattern in _PATTERNS.items():
        match = re.search(pattern, text)
        if not match:
            continue
        value = normalize_he(match.group(1)).strip(" .,")
        if not value:
            continue
        result.fields[key] = normalize_date(value) if key == "accident_date" else value

    match = re.search(_CASE_TYPE_PATTERN, text)
    if match:
        word = match.group(1).strip(' ."')
        if word in (CASE_TYPE_DEFENCE, CASE_TYPE_CLAIM):
            result.fields["case_type"] = word

    return result
