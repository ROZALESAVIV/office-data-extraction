"""File inspection, Hebrew handling, and the referral-email parser.

These run against the real sample documents where possible: a synthetic Hebrew
PDF proves nothing about what the insurer's portal actually produces.
"""

import io
import zipfile
from pathlib import Path

import pytest

from app.services import files, referral_email

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
pytestmark_samples = pytest.mark.skipif(
    not SAMPLES.exists(), reason="sample case files not present"
)


def _pdf_bytes() -> bytes:
    from pypdf import PdfWriter

    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def _docx_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", "<w:document/>")
        z.writestr("[Content_Types].xml", "<Types/>")
    return buf.getvalue()


# ── format detection ─────────────────────────────────────────────────────────


def test_detects_pdf():
    assert files.sniff_format(_pdf_bytes()) == "pdf"


def test_detects_docx():
    assert files.sniff_format(_docx_bytes()) == "docx"


def test_detects_eml():
    blob = b"Received: from x\r\nFrom: a@b.c\r\nSubject: hi\r\n\r\nbody"
    assert files.sniff_format(blob) == "eml"


def test_zip_without_word_part_is_rejected():
    """xlsx, pptx and plain archives are all zips too."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", "<workbook/>")
    with pytest.raises(files.UnsupportedFile):
        files.sniff_format(buf.getvalue())


def test_executable_renamed_to_pdf_is_rejected():
    """Detection is by content, so the extension is irrelevant."""
    with pytest.raises(files.UnsupportedFile):
        files.sniff_format(b"MZ\x90\x00\x03\x00\x00\x00executable")


def test_plain_text_is_rejected():
    with pytest.raises(files.UnsupportedFile):
        files.sniff_format("שלום עולם".encode())


# ── filename handling ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "given",
    ["../../../etc/passwd", "..\\..\\windows\\system32", "/etc/shadow", "....//evil.pdf"],
)
def test_traversal_attempts_are_flattened(given):
    out = files.sanitize_filename(given)
    assert "/" not in out and "\\" not in out
    assert not out.startswith(".")


def test_hebrew_filenames_survive():
    assert files.sanitize_filename("כתב_תביעה (1).pdf") == "כתב_תביעה (1).pdf"


def test_empty_filename_gets_a_default():
    assert files.sanitize_filename(None) == "document"
    assert files.sanitize_filename("   ") == "document"
    assert files.sanitize_filename("...") == "document"


def test_long_filename_is_truncated():
    assert len(files.sanitize_filename("x" * 500)) <= files.MAX_FILENAME_LENGTH


# ── Hebrew normalisation ─────────────────────────────────────────────────────


def test_normalise_strips_directionality_marks():
    assert files.normalize_he("‏שלום‎") == "שלום"


def test_normalise_strips_niqqud():
    assert files.normalize_he("שָׁלוֹם") == "שלום"


def test_normalise_folds_gershayim():
    assert files.normalize_he('בע״מ') == 'בע"מ'


def test_snippet_verification_matches_despite_marks():
    page = "‏המבוטח: אפי ושות 0202 בע״מ‎   כתובת: תל אביב"
    assert files.verify_snippet('אפי ושות 0202 בע"מ', page)


def test_snippet_verification_rejects_a_paraphrase():
    page = "המבוטח הוא חברת אפי ושות בערבון מוגבל"
    assert not files.verify_snippet("שם המבוטח הוא גורדון אהרון", page)


def test_snippet_verification_tolerates_ocr_noise():
    page = "סכום התביעה הוא 45,000 ש״ח נכון ליום הגשת התביעה"
    assert files.verify_snippet('סכום התביעה הוא 45,000 ש"ח נכון ליום', page)


# ── value normalisation ──────────────────────────────────────────────────────


def test_israeli_dates_are_day_first():
    """03/04/2026 is 3 April. A generic parser reads it as 4 March."""
    assert files.normalize_date("03/04/2026") == "2026-04-03"
    assert files.normalize_date("13.06.2025") == "2025-06-13"
    assert files.normalize_date("1-2-24") == "2024-02-01"


def test_hebrew_month_names():
    assert files.normalize_date("13 ביוני 2025") == "2025-06-13"


def test_impossible_date_is_rejected_not_guessed():
    assert files.normalize_date("32/13/2025") is None
    assert files.normalize_date("לא ידוע") is None


def test_amounts_drop_currency_and_separators():
    assert files.normalize_number("45,000 ₪") == "45000"
    assert files.normalize_number('1,234.56 ש"ח') == "1234.56"
    assert files.normalize_number("אין") is None


def test_id_numbers_keep_leading_zeros():
    """Stored as text: a dropped leading zero is a different person."""
    assert files.normalize_id_number("012345678") == "012345678"
    assert files.normalize_id_number("51-234567-8") == "512345678"


def test_normalize_value_dispatches_on_type():
    assert files.normalize_value("13/06/2025", "date") == "2025-06-13"
    assert files.normalize_value("45,000 ₪", "number") == "45000"
    assert files.normalize_value(" שלום  עולם ", "text") == "שלום עולם"


# ── against the real sample files ────────────────────────────────────────────


@pytestmark_samples
def test_every_sample_file_is_recognised():
    unknown = []
    for path in sorted(SAMPLES.glob("*/*")):
        if path.is_dir():
            continue
        try:
            files.sniff_format(path.read_bytes())
        except files.UnsupportedFile:
            unknown.append(path.name)
    assert unknown == [], f"unrecognised sample files: {unknown}"


@pytestmark_samples
def test_referral_emails_all_parse_completely():
    """Seven fields, six real emails, no model involved.

    If the insurer changes the template this fails here rather than silently
    producing empty cases.
    """
    required = (
        "direct_claim_number",
        "direct_policy_number",
        "insured_plate_number",
        "accident_date",
        "insured_name",
        "third_party_insurer",
        "case_type",
    )
    emails = sorted(SAMPLES.glob("*/*.eml"))
    assert emails, "no sample emails"
    for path in emails:
        parsed = referral_email.parse(path.read_bytes())
        missing = [k for k in required if not parsed.fields.get(k)]
        assert missing == [], f"{path.parent.name}: missing {missing}"
        assert parsed.case_type in ("הגנה", "תביעה")
        # accident_date must already be ISO
        assert files.parse_iso_date(parsed.fields["accident_date"]) is not None


@pytestmark_samples
def test_both_case_types_appear_in_the_samples():
    kinds = {referral_email.parse(p.read_bytes()).case_type for p in SAMPLES.glob("*/*.eml")}
    assert kinds == {"הגנה", "תביעה"}


def test_referral_parser_returns_nothing_rather_than_guessing():
    """A mail that is not the template must yield no fields at all."""
    blob = b"From: a@b.c\r\nSubject: lunch\r\n\r\nAre we still on for 1pm?"
    parsed = referral_email.parse(blob)
    assert parsed.fields == {}
    assert parsed.case_type is None


@pytestmark_samples
def test_pdf_stats_on_a_real_scan_and_a_real_text_pdf():
    scanned = next(SAMPLES.glob("*/*כתב תביעה*.pdf"), None)
    texty = next(SAMPLES.glob("*/*מפרט_פוליסה*.pdf"), None)
    if scanned:
        s = files.pdf_stats(scanned.read_bytes())
        assert s.page_count > 1
        assert s.text_extractable is False, "the pleading is a scan with no text layer"
    if texty:
        t = files.pdf_stats(texty.read_bytes())
        assert t.text_extractable is True


@pytestmark_samples
def test_page_window_slices_a_real_pdf():
    src = next(SAMPLES.glob("*/*מפרט_פוליסה*.pdf"))
    blob = src.read_bytes()
    total = files.pdf_stats(blob).page_count
    window = files.pdf_page_window(blob, 1, 2)
    assert files.pdf_stats(window).page_count == min(2, total)
