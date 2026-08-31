from __future__ import annotations

import types
from decimal import Decimal

from app.models.market_stats import MarketStatsCohort
from app.services.market_stats_service import batch_get_market_stats, cohort_key_for_listing


def _listing(make=None, model=None, year=None):
    return types.SimpleNamespace(make=make, model=model, year=year)


def test_cohort_key_normalizes_case_and_whitespace():
    key = cohort_key_for_listing(_listing(make=" Honda ", model=" Civic ", year=2020))
    assert key == ("honda", "civic", 2020)


def test_cohort_key_missing_make_returns_none():
    assert cohort_key_for_listing(_listing(make=None, model="civic", year=2020)) is None


def test_cohort_key_missing_model_returns_none():
    assert cohort_key_for_listing(_listing(make="honda", model=None, year=2020)) is None


def test_cohort_key_missing_year_returns_none():
    assert cohort_key_for_listing(_listing(make="honda", model="civic", year=None)) is None


def test_cohort_key_non_numeric_year_returns_none():
    assert cohort_key_for_listing(_listing(make="honda", model="civic", year="not-a-year")) is None


def test_cohort_key_blank_make_after_strip_returns_none():
    assert cohort_key_for_listing(_listing(make="   ", model="civic", year=2020)) is None


def _make_cohort(db, make, model, year, median=Decimal("50000"), p25=None, p75=None, sample_size=10):
    row = MarketStatsCohort(
        make=make,
        model=model,
        year=year,
        median_price=median,
        p25_price=p25,
        p75_price=p75,
        sample_size=sample_size,
    )
    db.add(row)
    db.commit()
    return row


def test_batch_get_market_stats_empty_listings_returns_empty_dict(db):
    assert batch_get_market_stats(db, []) == {}


def test_batch_get_market_stats_no_matching_cohort_returns_empty_dict(db):
    result = batch_get_market_stats(db, [_listing(make="honda", model="civic", year=2020)])
    assert result == {}


def test_batch_get_market_stats_returns_stats_for_matching_listing(db):
    _make_cohort(db, "honda", "civic", 2020, median=Decimal("60000"), sample_size=25)

    result = batch_get_market_stats(db, [_listing(make="Honda", model="Civic", year=2020)])
    stats = result[("honda", "civic", 2020)]
    assert stats.median_price == Decimal("60000")
    assert stats.sample_size == 25


def test_batch_get_market_stats_dedupes_repeated_keys_into_one_query(db):
    _make_cohort(db, "honda", "civic", 2020)

    listings = [
        _listing(make="honda", model="civic", year=2020),
        _listing(make="honda", model="civic", year=2020),
        _listing(make=None, model="civic", year=2020),
    ]
    result = batch_get_market_stats(db, listings)
    assert list(result.keys()) == [("honda", "civic", 2020)]


def test_batch_get_market_stats_handles_multiple_distinct_cohorts(db):
    _make_cohort(db, "honda", "civic", 2020, median=Decimal("60000"))
    _make_cohort(db, "vw", "polo", 2018, median=Decimal("40000"))

    listings = [
        _listing(make="honda", model="civic", year=2020),
        _listing(make="vw", model="polo", year=2018),
    ]
    result = batch_get_market_stats(db, listings)
    assert result[("honda", "civic", 2020)].median_price == Decimal("60000")
    assert result[("vw", "polo", 2018)].median_price == Decimal("40000")
