from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

_ALLOWED_CHARS_RE = re.compile(r"[^\d,\.-]")


def parse_price_decimal(value: Any) -> Decimal | None:
    """Parse flexible BR/EN price formats into Decimal (reais).

    Supported examples:
    - 189.990
    - 189.990,00
    - R$ 189.990
    - R$ 189.990,00
    - 189990
    - 189990.00
    """
    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, Decimal):
        return _validate_decimal(value)

    if isinstance(value, int):
        return _validate_decimal(Decimal(value))

    if isinstance(value, float):
        try:
            return _validate_decimal(Decimal(str(value)))
        except (InvalidOperation, ValueError):
            return None

    s = str(value).strip().replace("\xa0", " ")
    if not s:
        return None

    # Keep only digits and separators.
    token = _ALLOWED_CHARS_RE.sub("", s.replace(" ", ""))
    if not token or not any(ch.isdigit() for ch in token):
        return None

    sign = ""
    if token.startswith("-"):
        sign = "-"
    token = token.lstrip("+-")

    normalized = _normalize_numeric_token(token)
    if normalized is None:
        return None

    try:
        out = Decimal(f"{sign}{normalized}")
    except (InvalidOperation, ValueError):
        return None

    return _validate_decimal(out)


def parse_price_int_reais(value: Any) -> int | None:
    """Parse price and return integer reais.

    If centavos are non-zero, consider input ambiguous for this pipeline and return None.
    """
    dec = parse_price_decimal(value)
    if dec is None:
        return None

    if dec != dec.to_integral_value():
        return None

    out = int(dec)
    return out if out > 0 else None


def _normalize_numeric_token(token: str) -> str | None:
    if not token:
        return None

    if "," in token and "." in token:
        # Mixed separators: last separator is decimal separator.
        last_comma = token.rfind(",")
        last_dot = token.rfind(".")
        decimal_sep = "," if last_comma > last_dot else "."
        thousands_sep = "." if decimal_sep == "," else ","
        cleaned = token.replace(thousands_sep, "")
        if decimal_sep == ",":
            cleaned = cleaned.replace(",", ".")
        return cleaned

    if "," in token:
        return _normalize_single_separator(token, sep=",")

    if "." in token:
        return _normalize_single_separator(token, sep=".")

    return token


def _normalize_single_separator(token: str, *, sep: str) -> str | None:
    parts = token.split(sep)
    if any(p == "" for p in parts):
        return None

    if len(parts) > 2:
        # Multiple same separators are interpreted as thousands separators.
        return "".join(parts)

    left, right = parts
    if len(right) == 2:
        # Decimal format (e.g. 189990.00 / 189990,00)
        return f"{left}.{right}"

    if len(right) == 3 and left:
        # Thousands format (e.g. 189.990 / 189,990)
        return f"{left}{right}"

    # Fallback: treat as thousands-style grouping when unsure.
    return "".join(parts)


def _validate_decimal(value: Decimal) -> Decimal | None:
    if not value.is_finite() or value <= 0:
        return None
    return value
