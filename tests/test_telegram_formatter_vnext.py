from __future__ import annotations

from dataclasses import dataclass, field


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
    extras: dict = field(default_factory=dict)
    score_v2: int | None = None
    score_breakdown: dict | None = None


def test_formatter_complete_snapshot():
    from app.notifications.telegram_formatter import format_ad_message

    ad = _Ad(
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
        extras={"trim": "SI"},
        score_v2=87,
        score_breakdown={
            "total": 87,
            "delta_vs_median_pct": -0.08,
            "reasons": [
                "Preço 8% abaixo da mediana",
                "Match forte com sua wishlist",
                "Anúncio completo (boa confiabilidade)",
            ],
        },
    )

    payload = format_ad_message(ad)

    assert payload.text == (
        "🔥 87/100 — Honda Civic 2019 SI\n"
        "📍 São Paulo-SP | 🛞 75.352km | ⚙️ Manual | 💰 ↓8% vs med\n"
        "R$ 98.900,00 • Fonte: webmotors\n"
        "• Preço 8% abaixo da mediana\n"
        "• Match forte com sua wishlist\n"
        "• Anúncio completo (boa confiabilidade)"
    )

    assert payload.inline_keyboard and payload.inline_keyboard[0][0]["text"] == "Abrir anúncio"
    # URL no teclado é normalizado (tracking removido)
    assert "utm" not in payload.inline_keyboard[0][0]["url"]


def test_formatter_price_missing_snapshot():
    from app.notifications.telegram_formatter import format_ad_message

    ad = _Ad(
        source="olx",
        external_id="x2",
        url="https://olx.com.br/anuncio?id=2",
        title="Audi A4 2021",
        make="Audi",
        model="A4",
        year=2021,
        mileage_km=50000,
        transmission="Automático",
        location="Jandira-SP",
        price=None,
        thumbnail_url="https://img.exemplo.com/2.jpg",
        score_v2=65,
        score_breakdown={
            "total": 65,
            "caps_applied": ["cap_price_missing_65"],
            "reasons": ["Preço ausente reduz confiança"],
        },
    )

    payload = format_ad_message(ad)

    assert payload.text.splitlines()[0].startswith("🔥 65/100")
    assert "Preço: —" in payload.text.splitlines()[2]
    assert "Fonte: olx" in payload.text
    assert "• Preço ausente reduz confiança" in payload.text
    assert "http" not in payload.text  # URL fica no botão


def test_formatter_no_images_omits_delta_badge():
    from app.notifications.telegram_formatter import format_ad_message

    ad = _Ad(
        source="mobiauto",
        external_id="x3",
        url="https://mobiauto.com.br/a/3",
        title="Honda Civic 2018",
        make="Honda",
        model="Civic",
        year=2018,
        mileage_km=90000,
        transmission=None,
        location="Curitiba, PR",
        price=79900.0,
        thumbnail_url=None,
        score_v2=60,
        score_breakdown={
            "total": 60,
            "delta_vs_median_pct": -0.12,
            "reasons": ["Sem foto no anúncio (baixa confiança)"],
        },
    )

    payload = format_ad_message(ad)

    # sem foto => sem badge de delta
    assert "💰" not in payload.text
    assert "Sem foto" in payload.text



def test_formatter_km_missing_omits_badge_and_delta_when_not_provided():
    from app.notifications.telegram_formatter import format_ad_message

    ad = _Ad(
        source="gogarage",
        external_id="x4",
        url="https://gogarage.com.br/a/4",
        title="Volkswagen Golf GTI 2017",
        make="Volkswagen",
        model="Golf",
        year=2017,
        mileage_km=None,
        transmission="Automático",
        location="Porto Alegre, RS",
        price=149900.0,
        thumbnail_url="https://img.exemplo.com/4.jpg",
        score_v2=74,
        score_breakdown={
            "total": 74,
            "reasons": ["Match bom com sua wishlist"],
        },
    )

    payload = format_ad_message(ad)

    # sem KM => sem badge 🛞
    assert "🛞" not in payload.text
    # sem delta => sem 💰
    assert "💰" not in payload.text
    assert "⚙️" in payload.text
