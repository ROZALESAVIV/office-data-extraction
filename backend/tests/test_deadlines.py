"""The defence filing deadline.

A wrong date here is a missed filing, so every path is tested from both
directions and anything uncertain must return None rather than a guess.
"""

from datetime import date

import pytest

from app.reference.deadlines import days_to_file, defence_deadline

SERVED = date(2026, 3, 1)
FILED = date(2026, 2, 20)


# ── the procedure type, in every spelling that appears on real documents ─────


@pytest.mark.parametrize(
    "procedure",
    ['תא"מ', 'תאד"מ', "תאדמ", 'תא"מ 13051-05-26', "סדר דין מהיר",
     'תא"מ (תביעה בסדר דין מהיר)'],
)
def test_fast_track_is_45_days(procedure):
    assert days_to_file(procedure, None) == 45


@pytest.mark.parametrize(
    "procedure", ["ת.א.", 'ת"א', "ת.א. 12345-01-26", "סדר דין רגיל"]
)
def test_regular_track_is_60_days(procedure):
    assert days_to_file(procedure, None) == 60


def test_fast_track_is_not_mistaken_for_regular():
    """Regression: "תא" is a substring of "תא\"מ".

    Substring matching returned 60 days for a fast-track claim - fifteen days
    the lawyer does not actually have, which is the dangerous direction.
    """
    assert days_to_file('תא"מ', None) == 45, "must not fall through to the regular track"


def test_unrecognised_procedure_yields_nothing():
    assert days_to_file("משהו אחר", None) is None
    assert days_to_file("", None) is None


# ── the amount, when the procedure type is missing ───────────────────────────


def test_amount_decides_when_the_procedure_type_is_absent():
    assert days_to_file(None, 50_000) == 45
    assert days_to_file(None, 90_000) == 60


def test_the_85k_boundary_is_inclusive_of_the_fast_track():
    assert days_to_file(None, 85_000) == 45
    assert days_to_file(None, 85_000.01) == 60


def test_the_filed_procedure_type_beats_the_amount():
    """The court has already assigned the track; an odd amount does not move it."""
    assert days_to_file("ת.א.", 50_000) == 60
    assert days_to_file('תא"מ', 900_000) == 45


# ── which date the clock starts from ─────────────────────────────────────────


def test_the_summons_beats_a_derived_day_count():
    """Reading the number off the document is safer than inferring it."""
    result = defence_deadline(SERVED, "ת.א.", None, stated_days=45)
    assert result.days == 45 and result.days_source == "summons"
    assert result.date == date(2026, 4, 15)


def test_service_date_is_preferred_over_filing_date():
    result = defence_deadline(SERVED, 'תא"מ', None, 45, FILED)
    assert result.counted_from == "service"
    assert result.date == date(2026, 4, 15)
    assert result.is_cautious is False


def test_filing_date_is_the_fallback_when_service_is_unknown():
    """The "נתקבל" stamp is often simply absent - confirmed on real files."""
    result = defence_deadline(None, 'תא"מ', None, 45, FILED)
    assert result.counted_from == "filing"
    assert result.date == date(2026, 4, 6)
    assert result.is_cautious is True


def test_the_fallback_is_earlier_than_the_true_deadline():
    """Counting from filing errs early, which is the safe direction."""
    cautious = defence_deadline(None, 'תא"מ', None, 45, FILED)
    actual = defence_deadline(SERVED, 'תא"מ', None, 45, FILED)
    assert cautious.date < actual.date


# ── refusing to guess ────────────────────────────────────────────────────────


def test_no_dates_at_all_means_no_deadline():
    assert defence_deadline(None, 'תא"מ', None, 45, None) is None


def test_no_day_count_means_no_deadline():
    assert defence_deadline(SERVED, None, None, None, FILED) is None
    assert defence_deadline(SERVED, "", None, None, FILED) is None


def test_a_nonsense_day_count_is_ignored():
    """Falls back to the derived count rather than trusting a bad number."""
    assert defence_deadline(SERVED, 'תא"מ', None, 0, FILED).days == 45
    assert defence_deadline(SERVED, 'תא"מ', None, -5, FILED).days == 45
