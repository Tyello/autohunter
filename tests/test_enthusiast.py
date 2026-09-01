from __future__ import annotations

from app.core.enthusiast import compute_enthusiast_score, detect_signals, extract_year


def test_extract_year_finds_plausible_year():
    assert extract_year("Honda Civic Si 2001 impecável") == 2001


def test_extract_year_returns_none_when_absent():
    assert extract_year("Honda Civic Si impecável") is None


def test_extract_year_ignores_implausible_year():
    assert extract_year("lote 1899 sucata") is None


def test_detect_signals_flags_auction_keyword():
    sig = detect_signals("Leilão judicial Civic 2015")
    assert sig.is_auction is True
    assert sig.is_salvage is False


def test_detect_signals_flags_salvage_keyword():
    sig = detect_signals("Civic 2015 sinistro recuperado")
    assert sig.is_salvage is True


def test_detect_signals_uses_location_too():
    sig = detect_signals("Civic 2015", location="Copart auction yard")
    assert sig.is_auction is True


def test_score_penalizes_auction_and_salvage_heavily():
    clean = compute_enthusiast_score("Honda Civic Si 2018 manual")
    auctioned = compute_enthusiast_score("Honda Civic Si 2018 manual leilão")
    salvaged = compute_enthusiast_score("Honda Civic Si 2018 manual sinistro recuperado")
    assert auctioned < clean
    assert salvaged < clean


def test_score_rewards_enthusiast_trims_and_engine_codes():
    plain = compute_enthusiast_score("Honda Civic 2018")
    enthusiast = compute_enthusiast_score("Honda Civic Si 2018 turbo manual vtec")
    assert enthusiast > plain


def test_score_is_clamped_between_0_and_100():
    assert 0 <= compute_enthusiast_score(None) <= 100
    assert 0 <= compute_enthusiast_score("leilão sucata sinistro perda total 1900") <= 100
