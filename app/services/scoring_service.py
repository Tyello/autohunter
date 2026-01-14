from decimal import Decimal
from typing import Optional


def score_vs_fipe(price: Optional[Decimal], fipe: Optional[Decimal]) -> Optional[str]:
    if price is None or fipe is None:
        return None

    if price < fipe * Decimal("0.97"):
        return "abaixo"
    if price > fipe * Decimal("1.03"):
        return "acima"
    return "dentro"
