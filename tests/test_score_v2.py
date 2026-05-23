from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal


@dataclass
class _Wishlist:
    query: str
    filters: list = field(default_factory=list)


@dataclass
class _Ad:
    title: str
    url: str
    source: str = "webmotors"
    external_id: str = "x"
    make: str | None = None
    model: str | None = None
    version: str | None = None
    year: int | None = None
    price: Decimal | None = None
    mileage_km: int | None = None
    location: str | None = None
    city: str | None = None
    state: str | None = None
    transmission: str | None = None
    thumbnail_url: str | None = None
    extras: dict = field(default_factory=dict)


def _now():
    return datetime(2026, 2, 22, tzinfo=timezone.utc)


def _stats(sample=42):
    from app.scoring.types import MarketStats

    return MarketStats(make="honda", model="civic", year=2019, median_price=Decimal("100000"), p25_price=Decimal("95000"), p75_price=Decimal("110000"), sample_size=sample)


def _base_ad(price=Decimal("95000"), km=70000, img=True, location="São Paulo-SP"):
    return _Ad(title="Honda Civic SI 2019", url="https://x", make="Honda", model="Civic", version="SI", year=2019, price=price, mileage_km=km, location=location, transmission="Manual", thumbnail_url=("https://img" if img else None))


def test_market_price_below_median_improves_component_and_reason():
    from app.scoring.score_v2 import score_ad

    res = score_ad(_base_ad(price=Decimal("92000")), _Wishlist(query="civic si 2019"), _stats(), now=_now())
    assert res.components["market_price"] > 12
    assert any("abaixo da mediana" in r for r in res.reasons)


def test_market_price_above_median_penalizes_component():
    from app.scoring.score_v2 import score_ad

    res = score_ad(_base_ad(price=Decimal("118000")), _Wishlist(query="civic 2019"), _stats(), now=_now())
    assert res.components["market_price"] < 12


def test_market_stats_missing_or_small_sample_is_neutral():
    from app.scoring.score_v2 import score_ad

    no_stats = score_ad(_base_ad(), _Wishlist(query="civic"), None, now=_now())
    low_sample = score_ad(_base_ad(), _Wishlist(query="civic"), _stats(sample=3), now=_now())
    assert no_stats.components["market_price"] == 12
    assert low_sample.components["market_price"] == 12


def test_fipe_component_available_below_and_above():
    from app.scoring.score_v2 import score_ad

    below = score_ad(_base_ad(price=Decimal("92000")), _Wishlist(query="civic"), _stats(), fipe_price=Decimal("100000"), now=_now())
    above = score_ad(_base_ad(price=Decimal("109000")), _Wishlist(query="civic"), _stats(), fipe_price=Decimal("100000"), now=_now())
    assert below.components["fipe_price"] > 5
    assert above.components["fipe_price"] <= 5


def test_fipe_missing_is_neutral():
    from app.scoring.score_v2 import score_ad

    res = score_ad(_base_ad(), _Wishlist(query="civic"), _stats(), now=_now())
    assert res.components["fipe_price"] == 5


def test_rarity_bonus_and_neutral_without_sample():
    from app.scoring.score_v2 import score_ad

    rare = score_ad(_base_ad(), _Wishlist(query="civic"), _stats(), rarity_ratio=0.02, rarity_sample_size=30, now=_now())
    neutral = score_ad(_base_ad(), _Wishlist(query="civic"), _stats(), rarity_ratio=0.02, rarity_sample_size=2, now=_now())
    assert rare.components["rarity"] > 2
    assert neutral.components["rarity"] == 2


def test_quality_complete_vs_incomplete():
    from app.scoring.score_v2 import score_ad

    full = score_ad(_base_ad(), _Wishlist(query="civic"), _stats(), now=_now())
    poor = score_ad(_base_ad(price=None, km=None, img=False, location=""), _Wishlist(query="civic"), _stats(), now=_now())
    assert full.components["quality"] > poor.components["quality"]


def test_score_bounds_and_breakdown_stable():
    from app.scoring.score_v2 import score_ad

    res = score_ad(_base_ad(price=Decimal("1"), km=0), _Wishlist(query="civic"), _stats(), fipe_price=Decimal("100000"), rarity_ratio=0.01, rarity_sample_size=200, now=_now())
    assert 0 <= res.total <= 100
    assert set(["match", "market_price", "price", "fipe_price", "mileage", "rarity", "quality"]).issubset(res.components.keys())
    assert len(res.reasons) <= 3


def test_price_alias_does_not_double_count_total():
    from app.scoring.score_v2 import score_ad

    res = score_ad(_base_ad(), _Wishlist(query="civic"), _stats(), now=_now())
    assert res.components["price"] == res.components["market_price"]
    canonical_total = (
        res.components["match"]
        + res.components["market_price"]
        + res.components["fipe_price"]
        + res.components["mileage"]
        + res.components["rarity"]
        + res.components["quality"]
    )
    assert res.total == canonical_total


def test_neutral_base_score_no_inflation():
    from app.scoring.score_v2 import score_ad

    ad = _base_ad(price=Decimal("100000"), km=None, img=True, location="São Paulo-SP")
    res = score_ad(ad, _Wishlist(query="civic"), None, now=_now())
    # canonical neutral base (sem caps): match 35 + market 12 + fipe 5 + mileage 8 + rarity 2 + quality 6
    assert res.total == 68
