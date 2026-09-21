"""Pure file inspection and text handling. No network, no database.

Everything here works on bytes so it can be unit-tested without a server, a
bucket, or an API key.
"""

import difflib
import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

MAX_FILENAME_LENGTH = 120

# Formats we accept. 'eml' is the insurer's referral email, which carries more
# reliable field data than any of the documents it refers to.
SUPPORTED_FORMATS = ("pdf", "docx", "eml")

_MIME = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "eml": "message/rfc822",
}

# Headers that begin a real RFC-822 message. Checked against the first lines so
# a text file that merely mentions "Subject:" partway down is not mistaken for
# an email.
_EMAIL_HEADERS = (
    b"received:", b"from:", b"to:", b"subject:", b"date:",
    b"message-id:", b"mime-version:", b"return-path:", b"delivered-to:",
)


class UnsupportedFile(ValueError):
    """The bytes are not one of the formats we accept."""


# ── format detection ─────────────────────────────────────────────────────────


def sniff_format(blob: bytes) -> str:
    """Identify the format from the CONTENT, never the filename.

    A renamed executable must not be accepted because it ends in .pdf, and a
    correct file must not be rejected because someone stripped the extension.
    """
    if blob.startswith(b"%PDF-"):
        return "pdf"

    if blob.startswith(b"PK\x03\x04"):
        # A .docx is a zip; so is .xlsx, .pptx, .jar and a plain archive. Only
        # the presence of the Word document part makes it a Word file.
        try:
            with zipfile.ZipFile(io.BytesIO(blob)) as z:
                if "word/document.xml" in z.namelist():
                    return "docx"
        except zipfile.BadZipFile:
            pass
        raise UnsupportedFile("zip archive that is not a Word document")

    head = blob[:2048].lstrip()
    if head.startswith(b"\xef\xbb\xbf"):
        head = head[3:]
    for line in head.split(b"\n")[:12]:
        if line.lower().startswith(_EMAIL_HEADERS):
            return "eml"

    raise UnsupportedFile("not a PDF, Word document or email")


def mime_for(file_format: str) -> str:
    return _MIME[file_format]


def sanitize_filename(name: str | None) -> str:
    """Make a filename safe to display and store as a label.

    This value is shown to the lawyer and never used to build a storage path -
    the storage key is composed of UUIDs only - so this guards display and
    logging rather than being the last line of defence against traversal.
    """
    if not name:
        return "document"
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = unicodedata.normalize("NFC", name)
    name = re.sub(r"[^\w֐-׿.\-() \[\]]", "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    name = name[:MAX_FILENAME_LENGTH].strip(" .")
    return name or "document"


# ── PDF inspection ───────────────────────────────────────────────────────────

# Below this many non-whitespace characters per page, a PDF is a scan. Claude
# still reads it perfectly well; the flag only tells us whether we have a text
# layer to verify quotes against.
MIN_CHARS_PER_PAGE = 40


@dataclass(frozen=True)
class PdfStats:
    page_count: int
    text_extractable: bool


def pdf_stats(blob: bytes, sample_pages: int = 5) -> PdfStats:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(blob))
    pages = len(reader.pages)
    if pages == 0:
        return PdfStats(0, False)
    sampled = min(pages, sample_pages)
    chars = 0
    for page in reader.pages[:sampled]:
        try:
            chars += len(re.sub(r"\s", "", page.extract_text() or ""))
        except Exception:
            pass
    return PdfStats(pages, chars / sampled >= MIN_CHARS_PER_PAGE)


def pdf_page_text(blob: bytes) -> dict[int, str]:
    """Per-page text, 1-indexed.

    Used ONLY to check that a quote the model returned really appears on the
    page it claimed. It is never sent to the model: Hebrew text layers often
    come back in visual order, which would actively mislead it.
    """
    from pypdf import PdfReader

    out: dict[int, str] = {}
    reader = PdfReader(io.BytesIO(blob))
    for i, page in enumerate(reader.pages, start=1):
        try:
            out[i] = page.extract_text() or ""
        except Exception:
            out[i] = ""
    return out


def pdf_page_window(blob: bytes, first_page: int, last_page: int) -> bytes:
    """Slice a 1-indexed, inclusive page range into a new PDF."""
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(io.BytesIO(blob))
    writer = PdfWriter()
    for i in range(first_page - 1, min(last_page, len(reader.pages))):
        writer.add_page(reader.pages[i])
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


# ── Hebrew text ──────────────────────────────────────────────────────────────

_BIDI = dict.fromkeys(
    map(ord, "‎‏‪‫‬‭‮⁦⁧⁨⁩")
)
_NIQQUD = re.compile(r"[֑-ׇ]")


def normalize_he(s: str) -> str:
    """Normalise Hebrew for comparison.

    Strips directionality marks and vowel points, and folds the Hebrew
    gershayim/geresh onto ASCII quotes - without this, comparing a quote to the
    page text fails on differences that are not really differences.
    """
    s = unicodedata.normalize("NFC", s).translate(_BIDI)
    s = _NIQQUD.sub("", s)
    s = s.replace("״", '"').replace("׳", "'")
    s = s.replace("“", '"').replace("”", '"').replace("’", "'")
    return re.sub(r"\s+", " ", s).strip()


def verify_snippet(snippet: str, page_text: str, threshold: float = 0.85) -> bool:
    """Does this quote actually appear on that page?

    Exact containment first; otherwise the longest common run has to cover most
    of the quote, which tolerates OCR noise without accepting a paraphrase.
    """
    if not snippet or not page_text:
        return False
    a, b = normalize_he(snippet), normalize_he(page_text)
    if not a:
        return False
    if a in b:
        return True
    match = difflib.SequenceMatcher(None, a, b, autojunk=False).find_longest_match(
        0, len(a), 0, len(b)
    )
    return match.size >= len(a) * threshold


# ── value normalisation ──────────────────────────────────────────────────────

_HEB_MONTHS = {
    "ינואר": 1, "פברואר": 2, "מרץ": 3, "מרס": 3, "אפריל": 4, "מאי": 5, "יוני": 6,
    "יולי": 7, "אוגוסט": 8, "ספטמבר": 9, "אוקטובר": 10, "נובמבר": 11, "דצמבר": 12,
}


def normalize_date(value: str) -> str | None:
    """Parse an Israeli date to ISO ``YYYY-MM-DD``.

    Israeli dates are DAY first. A generic parser reads 03/04/2026 as 4 March,
    which is a different day in the same plausible range - the kind of error
    nobody notices until a deadline is missed.
    """
    if not value:
        return None
    s = normalize_he(str(value))

    m = re.search(r"\b(\d{1,2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{2,4})\b", s)
    if m:
        day, month, year = (int(g) for g in m.groups())
        if year < 100:
            year += 2000
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            return None

    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", s)
    if m:
        try:
            return date(*(int(g) for g in m.groups())).isoformat()
        except ValueError:
            return None

    m = re.search(r"\b(\d{1,2})\s*(?:ב)?([א-ת]+)\s*,?\s*(\d{4})\b", s)
    if m and m.group(2) in _HEB_MONTHS:
        try:
            return date(int(m.group(3)), _HEB_MONTHS[m.group(2)], int(m.group(1))).isoformat()
        except ValueError:
            return None
    return None


def normalize_number(value: str) -> str | None:
    """Strip currency and separators; return a canonical decimal string."""
    if value is None:
        return None
    s = normalize_he(str(value))
    s = s.replace("₪", " ").replace('ש"ח', " ").replace("שח", " ").replace("NIS", " ")
    s = s.replace(",", "")
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        return None
    try:
        return str(Decimal(m.group(0)))
    except InvalidOperation:
        return None


def normalize_id_number(value: str) -> str | None:
    """Israeli ID / company number.

    Kept as text: storing it as a number silently drops leading zeros, and an
    ID with a missing leading zero is a different person.
    """
    if value is None:
        return None
    s = re.sub(r"[^\d]", "", normalize_he(str(value)))
    return s or None


def normalize_value(value: str | None, data_type: str) -> str | None:
    if value is None:
        return None
    if data_type == "date":
        return normalize_date(value)
    if data_type == "number":
        return normalize_number(value)
    text = normalize_he(str(value))
    return text or None


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None
