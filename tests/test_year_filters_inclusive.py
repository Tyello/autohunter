import pytest

from app.services.wishlists_service import (
    _extract_year_directives,
    numeric_filter_match,
    year_in_directive_range,
)


@pytest.mark.parametrize(
    "op,value,target,expected",
    [
        ("gte", 2014, 2014, True),
        ("lte", 2015, 2015, True),
        ("gt", 2014, 2014, False),
        ("lt", 2015, 2015, False),
        ("eq", 2014, 2014, True),
        ("neq", 2014, 2015, True),
    ],
)
def test_numeric_filter_match_contract(op, value, target, expected):
    assert numeric_filter_match(value, op, target) is expected


def test_extract_year_range_between_is_inclusive_on_bounds():
    q, ymin, ymax = _extract_year_directives("civic entre 2014 e 2015")
    assert q.strip() == "civic"
    assert ymin == 2014
    assert ymax == 2015

    # INCLUSIVO: 2014 e 2015 entram
    assert year_in_directive_range(2014, ymin, ymax) is True
    assert year_in_directive_range(2015, ymin, ymax) is True
    # fora do range não entra
    assert year_in_directive_range(2013, ymin, ymax) is False
    assert year_in_directive_range(2016, ymin, ymax) is False


def test_extract_year_range_ate_is_inclusive():
    q, ymin, ymax = _extract_year_directives("civic até 2015")
    assert q.strip() == "civic"
    assert ymin is None
    assert ymax == 2015

    assert year_in_directive_range(2015, ymin, ymax) is True  # INCLUSIVO
    assert year_in_directive_range(2016, ymin, ymax) is False


def test_extract_year_range_ate_without_accent_is_inclusive():
    q, ymin, ymax = _extract_year_directives("civic ate 2015")
    assert q.strip() == "civic"
    assert ymin is None
    assert ymax == 2015

    assert year_in_directive_range(2015, ymin, ymax) is True  # INCLUSIVO
    assert year_in_directive_range(2014, ymin, ymax) is True


def test_extract_year_range_hyphen_is_inclusive():
    q, ymin, ymax = _extract_year_directives("civic 2014-2015")
    assert q.strip() == "civic"
    assert ymin == 2014
    assert ymax == 2015

    assert year_in_directive_range(2014, ymin, ymax) is True
    assert year_in_directive_range(2015, ymin, ymax) is True


def test_extract_year_range_swapped_is_normalized():
    q, ymin, ymax = _extract_year_directives("civic entre 2015 e 2014")
    assert q.strip() == "civic"
    assert ymin == 2014
    assert ymax == 2015

    assert year_in_directive_range(2014, ymin, ymax) is True
    assert year_in_directive_range(2015, ymin, ymax) is True
