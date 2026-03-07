from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


@dataclass
class _Ad:
    source: str
    external_id: str
    url: str
    title: str | None = None
    make: str | None = None
    model: str | None = None
    year: int | None = None
    mileage_km: int | None = None
    transmission: str | None = None
    location: str | None = None
    price: float | None = None
    thumbnail_url: str | None = None
    description: str | None = None
    seller_type: str | None = None
    published_at: datetime | None = None
    extras: dict = field(default_factory=dict)
    score_v2: int | None = None
    score_breakdown: dict | None = None


def _base_ad(**kwargs):
    data = dict(
        source="webmotors",
        external_id="x1",
        url="https://www.webmotors.com.br/comprar/1?utm=track#frag",
        title="Honda Civic SI 2019",
        make="Honda",
        model="Civic",
        year=2019,
        mileage_km=75352,
        transmission="Manual",
        location="São Paulo, SP",
        price=98900.0,
        thumbnail_url="https://img.exemplo.com/1.jpg",
        seller_type="particular",
        score_v2=87,
        score_breakdown={
            "total": 87,
            "delta_vs_median_pct": -0.08,
            "reasons": [
                "Preço 8% abaixo da mediana",
                "Match forte com sua wishlist",
                "Anúncio completo",
                "extra que deve ser cortado",
            ],
        },
        extras={"trim": "SI"},
    )
    data.update(kwargs)
    return _Ad(**data)


def test_complete_score_gt_zero_snapshot_and_order():
    from app.notifications.telegram_formatter import format_ad_message

    ad = _base_ad(
        published_at=datetime.now(timezone.utc) - timedelta(hours=3),
        extras={"trim": "SI", "published_at_reliable": True},
    )

    payload = format_ad_message(ad)
    lines = payload.text.splitlines()

    assert lines[0] == "🔥 87/100 — Honda Civic 2019 SI"
    assert lines[1].startswith("📍 São Paulo-SP | ⏱️ Há 3h | 🛞 75.352 km | ⚙️ Manual | 💰 -8% vs mediana | 👤 Particular")
    assert lines[2] == "R$ 98.900,00 • Fonte: webmotors"
    assert lines[3:] == [
        "• Preço 8% abaixo da mediana",
        "• Match forte com sua wishlist",
        "• Anúncio completo",
    ]
    assert payload.inline_keyboard == [[{"text": "Abrir anúncio", "url": "https://www.webmotors.com.br/comprar/1"}]]


def test_score_zero_hides_score_and_reasons():
    from app.notifications.telegram_formatter import format_ad_message

    ad = _base_ad(score_v2=0, score_breakdown={"total": 0, "reasons": ["não deve aparecer"]})
    payload = format_ad_message(ad)

    assert payload.text.splitlines()[0] == "Honda Civic 2019 SI"
    assert "🔥" not in payload.text
    assert all(not ln.startswith("• ") for ln in payload.text.splitlines())


def test_missing_km_omits_badge():
    from app.notifications.telegram_formatter import format_ad_message

    payload = format_ad_message(_base_ad(mileage_km=None))
    assert "🛞" not in payload.text


def test_missing_transmission_omits_badge():
    from app.notifications.telegram_formatter import format_ad_message

    payload = format_ad_message(_base_ad(transmission=None))
    assert "⚙️" not in payload.text


def test_missing_price_shows_dash_and_no_invented_data():
    from app.notifications.telegram_formatter import format_ad_message

    payload = format_ad_message(_base_ad(price=None))
    assert "— • Fonte: webmotors" in payload.text


def test_missing_delta_omits_badge():
    from app.notifications.telegram_formatter import format_ad_message

    payload = format_ad_message(_base_ad(score_breakdown={"total": 80, "reasons": ["ok"]}))
    assert "💰" not in payload.text


def test_long_title_truncates_intelligently():
    from app.notifications.telegram_formatter import build_title

    title = build_title(_base_ad(make=None, model=None, title="Audi " + ("A" * 140)))
    assert title.endswith("…")
    assert len(title) <= 91


def test_recency_badge_when_reliable():
    from app.notifications.telegram_formatter import format_ad_message

    ad = _base_ad(
        published_at=datetime.now(timezone.utc) - timedelta(days=1, hours=1),
        extras={"trim": "SI", "published_at_reliable": True},
    )
    payload = format_ad_message(ad)
    assert "⏱️ Ontem" in payload.text


def test_no_recency_badge_when_unreliable():
    from app.notifications.telegram_formatter import format_ad_message

    ad = _base_ad(published_at=datetime.now(timezone.utc) - timedelta(hours=4), extras={"trim": "SI"})
    payload = format_ad_message(ad)
    assert "⏱️" not in payload.text


def test_detect_leilao_positive():
    from app.notifications.telegram_formatter import format_ad_message

    ad = _base_ad(description="veículo de leilão com desconto")
    payload = format_ad_message(ad)
    assert "⚠️ Leilão" in payload.text


def test_ignore_negated_leilao():
    from app.notifications.telegram_formatter import format_ad_message

    ad = _base_ad(description="não é de leilão, sem leilão")
    payload = format_ad_message(ad)
    assert "⚠️ Leilão" not in payload.text


def test_detect_monta_media_and_blindado():
    from app.notifications.telegram_formatter import format_ad_message

    ad = _base_ad(description="carro com pequena monta e média monta, blindagem nível 3")
    payload = format_ad_message(ad)
    assert "⚠️ Pequena monta" in payload.text
    assert "⚠️ Média monta" in payload.text
    assert "🛡️ Blindado" in payload.text


def test_seller_type_badges_store_and_private():
    from app.notifications.telegram_formatter import format_ad_message

    loja = format_ad_message(_base_ad(seller_type="loja"))
    particular = format_ad_message(_base_ad(seller_type="particular"))
    assert "🏪 Loja" in loja.text
    assert "👤 Particular" in particular.text


def test_single_open_button_only():
    from app.notifications.telegram_formatter import format_ad_message

    payload = format_ad_message(_base_ad())
    assert len(payload.inline_keyboard) == 1
    assert len(payload.inline_keyboard[0]) == 1
    assert payload.inline_keyboard[0][0]["text"] == "Abrir anúncio"
