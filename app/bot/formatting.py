from decimal import Decimal
from typing import Optional


def format_price(value: Optional[Decimal]) -> str:
    if value is None:
        return "—"
    # simples (sem i18n agora)
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
