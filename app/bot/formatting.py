from decimal import Decimal
from typing import Optional


def format_price(value: Optional[Decimal]) -> str:
    if value is None:
        return "—"
    # simples (sem i18n agora)
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def format_score(price, fipe_price) -> str:
    if price is None or fipe_price is None:
        return "Score: —"

    # score simples
    if price < fipe_price * Decimal("0.97"):
        return "Score: abaixo da FIPE"
    if price > fipe_price * Decimal("1.03"):
        return "Score: acima da FIPE"
    return "Score: dentro da FIPE"
