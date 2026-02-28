from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime, timezone


@dataclass
class _Wishlist:
    query: str
    filters: list = field(default_factory=list)


@dataclass
class _Ad:
    source: str
    external_id: str
    url: str
    title: str
    make: str
    model: str
    year: int
    price: Decimal | None
    mileage_km: int | None
    location: str | None
    transmission: str | None
    thumbnail_url: str | None
    extras: dict = field(default_factory=dict)


class _View:
    def __init__(self, ad, score_v2, score_breakdown):
        self._ad = ad
        self.score_v2 = score_v2
        self.score_breakdown = score_breakdown

    def __getattr__(self, item):
        return getattr(self._ad, item)


def test_integration_score_to_message_contains_badges_and_reasons():
    from app.scoring.score_v2 import score_ad
    from app.scoring.types import MarketStats
    from app.notifications.telegram_formatter import format_ad_message

    now = datetime(2026, 2, 22, tzinfo=timezone.utc)

    ad = _Ad(
        source="webmotors",
        external_id="x1",
        url="https://www.webmotors.com.br/comprar/1?utm=track#frag",
        title="Honda Civic SI 2019",
        make="Honda",
        model="Civic",
        year=2019,
        price=Decimal("92000"),
        mileage_km=70000,
        location="São Paulo, SP",
        transmission="Manual",
        thumbnail_url="https://img.exemplo.com/1.jpg",
        extras={"trim": "SI"},
    )
    w = _Wishlist(query="civic si 2019")
    stats = MarketStats(make="honda", model="civic", year=2019, median_price=Decimal("100000"), sample_size=50)

    sres = score_ad(ad, w, stats, now=now)
    payload = format_ad_message(_View(ad, sres.total, sres.to_dict()))

    # badges
    assert "📍" in payload.text
    assert "🛞" in payload.text
    assert "⚙️" in payload.text
    assert "💰" in payload.text

    # reasons
    assert "•" in payload.text
    assert any("mediana" in line for line in payload.text.splitlines() if line.startswith("•"))

    # URL no corpo não deve existir
    assert "http" not in payload.text
