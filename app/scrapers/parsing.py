import re
from decimal import Decimal, InvalidOperation
from typing import Optional


# DB column is NUMERIC(12, 2): absolute value must be < 10^10.
_MAX_DB_PRICE = Decimal("9999999999.99")

# Prefer explicit currency marker (Brazil).
_BRL_AFTER_RS_RE = re.compile(
    r"R\$\s*([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]{2})?|[0-9]+(?:,[0-9]{2})?)",
    re.IGNORECASE,
)

# Fallback: accept only values that look like real prices (avoid years/engine sizes).
# - either has thousand separators (ex: 85.900, 1.234.567,89)
# - or has at least 5 digits (ex: 12500)
_BRL_PRICE_FALLBACK_RE = re.compile(
    r"\b(\d{1,3}(?:\.[0-9]{3})+(?:,[0-9]{2})?|\d{5,}(?:,[0-9]{2})?)\b"
)


def _to_decimal_brl(num: str) -> Optional[Decimal]:
    if not num:
        return None
    t = num.strip().replace("\xa0", " ")

    # Keep only digits and separators within the captured number.
    t = re.sub(r"[^\d\.,]", "", t)
    if not t:
        return None

    # Normal BR formats: 85.900 ; 88.999,00 ; 1.234.567,89
    t = t.replace(".", "").replace(",", ".")

    try:
        v = Decimal(t)
    except (InvalidOperation, ValueError):
        return None

    # Safety: protect the DB and ignore nonsense values.
    if not v.is_finite() or v <= 0 or v > _MAX_DB_PRICE:
        return None

    # Normalize scale to 2 decimals to match the DB.
    try:
        return v.quantize(Decimal("0.01"))
    except Exception:
        return v


def parse_brl_price(text: str) -> Optional[Decimal]:
    """
    Recebe algo tipo "R$ 85.900" ou "85.900" e converte para Decimal.
    Retorna None se não conseguir.
    """
    if not text:
        return None

    t = (text or "").strip().replace("\xa0", " ")
    if not t:
        return None

    # Best-case: explicit currency marker.
    m = _BRL_AFTER_RS_RE.search(t)
    if m:
        return _to_decimal_brl(m.group(1))

    # Fallback: look for a "price-looking" number and parse it.
    # Use the largest plausible candidate (helps when multiple numbers appear).
    cands = []
    for m2 in _BRL_PRICE_FALLBACK_RE.finditer(t):
        v = _to_decimal_brl(m2.group(1))
        if v is not None:
            cands.append(v)
    if not cands:
        return None
    return max(cands)
