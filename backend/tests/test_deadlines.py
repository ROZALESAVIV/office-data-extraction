"""The defence filing deadline.

A wrong date here means a missed filing deadline, so the rule is tested from
both directions and every uncertain case must return None rather than a guess.
"""

from datetime import date

import pytest

from app.reference.deadlines import days_to_file, defence_deadline

SERVED = date(2026, 3, 1)


@pytest.mark.parametrize("procedure", ['תאד"מ', "תאדמ", "סדר דין מהיר"])
def test_fast_track_is_45_days(procedure):
    assert defence_deadline(SERVED, procedure) == date(2026, 4, 15)


@pytest.mark.parametrize("procedure", ["ת.א.", 'ת"א', "סדר דין רגיל"])
def test_regular_track_is_60_days(procedure):
    assert defence_deadline(SERVED, procedure) == date(2026, 4, 30)


def test_amount_decides_when_the_procedure_type_is_missing():
    assert defence_deadline(SERVED, None, 50_000) == date(2026, 4, 15)
    assert defence_deadline(SERVED, None, 90_000) == date(2026, 4, 30)


def test_the_85k_boundary_is_inclusive_of_the_fast_track():
    assert days_to_file(None, 85_000) == 45
    assert days_to_file(None, 85_000.01) == 60


def test_the_filed_procedure_type_beats_the_amount():
    """The court has already assigned the track; an odd amount does not move it."""
    assert defence_deadline(SERVED, "ת.א.", 50_000) == date(2026, 4, 30)
    assert defence_deadline(SERVED, 'תאד"מ', 900_000) == date(2026, 4, 15)


def test_no_service_date_means_no_deadline():
    """The stamp is often missing or illegible. An empty field is a real answer."""
    assert defence_deadline(None, 'תאד"מ') is None


def test_nothing_known_means_no_deadline():
    assert defence_deadline(SERVED) is None
    assert defence_deadline(SERVED, "", None) is None


def test_unrecognised_procedure_falls_back_to_the_amount():
    assert defence_deadline(SERVED, "משהו אחר", 50_000) == date(2026, 4, 15)


def test_unrecognised_procedure_and_no_amount_is_none():
    assert defence_deadline(SERVED, "משהו אחר") is None
