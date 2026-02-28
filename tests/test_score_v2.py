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
    year: int | None = None
    price: Decimal | None = None
    mileage_km: int | None = None
    location: str | None = None
    transmission: str | None = None
    thumbnail_url: str | None = None
    extras: dict = field(default_factory=dict)


def _now():
    return datetime(2026, 2, 22, tzinfo=timezone.utc)


def test_score_price_below_median_increases_and_reason():
    from app.scoring.score_v2 import score_ad
    from app.scoring.types import MarketStats

    ad = _Ad(
        title="Honda Civic SI 2019",
        url="https://x",
        make="Honda",
        model="Civic",
        year=2019,
        price=Decimal("92000"),
        mileage_km=70000,
        location="São Paulo-SP",
        transmission="Manual",
        thumbnail_url="https://img",
    )
    w = _Wishlist(query="civic si 2019")

    stats = MarketStats(
        make="honda",
        model="civic",
        year=2019,
        median_price=Decimal("100000"),
        p25_price=Decimal("95000"),
        p75_price=Decimal("110000"),
        sample_size=42,
    )

    res = score_ad(ad, w, stats, now=_now())

    assert res.delta_vs_median_pct is not None and res.delta_vs_median_pct < 0
    assert any("abaixo da mediana" in r for r in res.reasons)
    assert res.components["price"] > 17  # neutral is ~17


def test_score_price_missing_caps_65_and_reason():
    from app.scoring.score_v2 import score_ad

    ad = _Ad(
        title="Audi A4 2021",
        url="https://x",
        make="Audi",
        model="A4",
        year=2021,
        price=None,
        mileage_km=40000,
        location="Jandira-SP",
        thumbnail_url="https://img",
    )
    w = _Wishlist(query="a4 2021")

    res = score_ad(ad, w, None, now=_now())
    assert res.total <= 65
    assert "cap_price_missing_65" in res.caps_applied
    assert any("Preço ausente" in r for r in res.reasons)


def test_score_no_images_caps_60_and_reason():
    from app.scoring.score_v2 import score_ad

    ad = _Ad(
        title="Honda Civic 2018",
        url="https://x",
        make="Honda",
        model="Civic",
        year=2018,
        price=Decimal("80000"),
        mileage_km=90000,
        location="Curitiba-PR",
        thumbnail_url=None,
    )
    w = _Wishlist(query="civic 2018")

    res = score_ad(ad, w, None, now=_now())
    assert res.total <= 60
    assert "cap_images_missing_60" in res.caps_applied
    assert any("Sem foto" in r for r in res.reasons)


def test_score_high_km_penalizes_mileage_component():
    from app.scoring.score_v2 import score_ad

    ad = _Ad(
        title="Honda Civic 2019",
        url="https://x",
        make="Honda",
        model="Civic",
        year=2019,
        price=Decimal("95000"),
        mileage_km=250000,
        location="São Paulo-SP",
        thumbnail_url="https://img",
    )
    w = _Wishlist(query="civic 2019")

    res = score_ad(ad, w, None, now=_now())
    assert res.components["mileage"] <= 8
    assert any("KM alto" in r for r in res.reasons)


def test_score_no_history_price_neutral():
    from app.scoring.score_v2 import score_ad
    from app.scoring.types import MarketStats

    ad = _Ad(
        title="Honda Civic 2019",
        url="https://x",
        make="Honda",
        model="Civic",
        year=2019,
        price=Decimal("95000"),
        mileage_km=90000,
        location="São Paulo-SP",
        thumbnail_url="https://img",
    )
    w = _Wishlist(query="civic 2019")

    stats = MarketStats(
        make="honda",
        model="civic",
        year=2019,
        median_price=Decimal("100000"),
        sample_size=3,  # insufficient
    )

    res = score_ad(ad, w, stats, now=_now())
    assert res.delta_vs_median_pct is None
    assert res.components["price"] == 17
