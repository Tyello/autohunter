from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from app.core.text_norm import tokens as _tokens

from .types import MarketStats, ScoreResult


# Stopwords leves: melhora recall/robustez sem NLP pesado.
_STOPWORDS = {
    "a", "o", "os", "as", "de", "do", "da", "dos", "das", "e", "em", "no", "na", "nos", "nas",
    "para", "por", "com", "sem", "ate", "até", "entre", "apenas", "so", "só", "somente",
    "partir", "apartir", "desde", "ano", "year", "anos", "valor", "preco", "preço",
}

_RE_YEAR = re.compile(r"^(19\d{2}|20\d{2})$")


def _is_year_token(t: str) -> bool:
    return bool(t) and bool(_RE_YEAR.match(t))


def _expand_alphanum_pairs(ts: list[str]) -> set[str]:
    """Covers 'A 6' vs 'A6', '320 i' vs '320i'."""
    out: set[str] = set()
    for i in range(len(ts) - 1):
        a, b = ts[i], ts[i + 1]
        if not a or not b:
            continue
        if a.isalpha() and len(a) <= 3 and b.isdigit() and len(b) <= 4:
            out.add(a + b)
        if a.isdigit() and len(a) <= 4 and b.isalpha() and len(b) <= 3:
            out.add(a + b)
    return out


def _extract_year_from_text(text: str) -> int | None:
    if not text:
        return None
    m = re.search(r"\b(19\d{2}|20\d{2})\b", text)
    if not m:
        return None
    try:
        y = int(m.group(1))
        if 1900 <= y <= 2100:
            return y
    except Exception:
        return None
    return None


def _extract_year_from_url(url: str) -> int | None:
    if not url:
        return None
    m = re.search(r"(?:/|\b)(19\d{2}|20\d{2})(?:/|\b|\?|#)", url)
    if not m:
        return None
    try:
        y = int(m.group(1))
        if 1900 <= y <= 2100:
            return y
    except Exception:
        return None
    return None


def _ad_year(ad: Any) -> int | None:
    # Prefer structured field
    try:
        y = getattr(ad, "year", None)
        if y is not None:
            y = int(y)
            if 1900 <= y <= 2100:
                return y
    except Exception:
        pass

    # Fallback: title then url
    y2 = _extract_year_from_text(getattr(ad, "title", "") or "")
    if y2:
        return y2
    return _extract_year_from_url(getattr(ad, "url", "") or "")


def _ad_has_images(ad: Any) -> bool:
    if getattr(ad, "thumbnail_url", None):
        return True
    extras = getattr(ad, "extras", None) or {}
    if isinstance(extras, dict):
        imgs = extras.get("images") or extras.get("image_urls") or extras.get("photos")
        if isinstance(imgs, (list, tuple)) and len(imgs) > 0:
            return True
    return False


def _effective_terms(query: str) -> list[str]:
    ts = _tokens(query or "")
    return [t for t in ts if t and t not in _STOPWORDS]


def _clamp(n: float, lo: float, hi: float) -> float:
    return lo if n < lo else hi if n > hi else n


def _fmt_pct(p: float) -> str:
    # 0.082 -> '8%'
    try:
        v = int(round(abs(p) * 100.0))
    except Exception:
        v = 0
    return f"{v}%"


def _as_decimal(v: Any) -> Decimal | None:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return v
    if isinstance(v, (int, float)):
        try:
            return Decimal(str(v))
        except Exception:
            return None
    try:
        return Decimal(str(v))
    except Exception:
        return None


def score_ad(
    ad: Any,
    wishlist: Any,
    market_stats: MarketStats | None,
    *,
    now: datetime | None = None,
    min_market_sample: int = 8,
) -> ScoreResult:
    """Compute v2 score (0-100) with breakdown.

    This function is designed to be fast and deterministic.
    """

    now = now or datetime.now(timezone.utc)

    # --- Match (0-35) ---
    query = getattr(wishlist, "query", "") if wishlist is not None else ""
    terms = _effective_terms(query or "")

    # If there are other terms, do not let an isolated year reduce match.
    if any(not _is_year_token(t) for t in terms):
        terms = [t for t in terms if not _is_year_token(t)]

    base = " ".join([
        getattr(ad, "title", "") or "",
        getattr(ad, "location", "") or "",
        getattr(ad, "make", "") or "",
        getattr(ad, "model", "") or "",
    ])

    ht_list = _tokens(base)
    hay_tokens = set(ht_list)
    hay_tokens |= _expand_alphanum_pairs(ht_list)

    year = _ad_year(ad)

    if not terms:
        match_score = 35
        match_ratio = 1.0
    else:
        sat = 0
        for t in terms:
            if not t:
                continue
            if _is_year_token(t) and year is not None:
                try:
                    sat += 1 if int(t) == int(year) else 0
                except Exception:
                    pass
            else:
                sat += 1 if t in hay_tokens else 0

        match_ratio = sat / max(1, len(terms))
        match_score = int(round(_clamp(match_ratio, 0.0, 1.0) * 35.0))

    # --- Price (0-35) ---
    price_dec = _as_decimal(getattr(ad, "price", None))
    delta_pct: float | None = None
    price_score: int
    market_context: dict[str, Any] | None = None

    if price_dec is not None and market_stats is not None and int(market_stats.sample_size or 0) >= int(min_market_sample):
        med = market_stats.median_price
        if med and med > 0:
            delta_pct = float((price_dec - med) / med)  # +0.10 => 10% acima da mediana
            # clamp to +/-25% for a stable linear mapping
            d = _clamp(delta_pct, -0.25, 0.25)
            # delta=-25% => 35, delta=0 => ~18, delta=+25% => 0
            price_score = int(round(((-d + 0.25) / 0.5) * 35.0))
            price_score = max(0, min(35, price_score))

            market_context = {
                "median": float(market_stats.median_price),
                "p25": float(market_stats.p25_price) if market_stats.p25_price is not None else None,
                "p75": float(market_stats.p75_price) if market_stats.p75_price is not None else None,
                "sample_size": int(market_stats.sample_size or 0),
                "cohort": f"{market_stats.make}|{market_stats.model}|{market_stats.year}",
                "delta_pct": delta_pct,
            }
        else:
            price_score = 17
    else:
        # Neutral when missing price or insufficient history
        price_score = 17
        if market_stats is not None:
            market_context = {
                "median": float(market_stats.median_price) if market_stats.median_price is not None else None,
                "p25": float(market_stats.p25_price) if market_stats.p25_price is not None else None,
                "p75": float(market_stats.p75_price) if market_stats.p75_price is not None else None,
                "sample_size": int(market_stats.sample_size or 0),
                "cohort": f"{market_stats.make}|{market_stats.model}|{market_stats.year}",
                "delta_pct": None,
            }

    # --- Mileage (0-20) ---
    km = getattr(ad, "mileage_km", None)
    try:
        km = int(km) if km is not None else None
    except Exception:
        km = None

    mileage_score = 10  # neutral
    km_per_year: int | None = None

    if km is not None and km >= 0 and year is not None and year <= now.year:
        age = max(1, now.year - year)
        km_per_year = int(round(km / age))

        # Piecewise linear mapping (cheap): lower km/year is better.
        if km_per_year <= 8000:
            mileage_score = 20
        elif km_per_year <= 15000:
            # 8k..15k -> 20..15
            mileage_score = int(round(20 - (km_per_year - 8000) / 7000 * 5))
        elif km_per_year <= 25000:
            # 15k..25k -> 15..8
            mileage_score = int(round(15 - (km_per_year - 15000) / 10000 * 7))
        elif km_per_year <= 40000:
            # 25k..40k -> 8..0
            mileage_score = int(round(8 - (km_per_year - 25000) / 15000 * 8))
        else:
            mileage_score = 0

        mileage_score = max(0, min(20, mileage_score))

    # --- Quality (0-10) ---
    quality = 10
    if price_dec is None:
        quality -= 3
    if km is None:
        quality -= 2
    if not (getattr(ad, "location", None) or "").strip():
        quality -= 1
    if not _ad_has_images(ad):
        quality -= 3
    url = (getattr(ad, "url", None) or "").strip()
    if not url.startswith("http"):
        quality -= 1

    quality = max(0, min(10, quality))

    components = {
        "match": int(match_score),
        "price": int(price_score),
        "mileage": int(mileage_score),
        "quality": int(quality),
    }

    raw_total = int(sum(components.values()))

    # --- Hard caps ---
    caps: list[tuple[int, str]] = []
    has_images = _ad_has_images(ad)

    if price_dec is None:
        caps.append((65, "cap_price_missing_65"))
    if not has_images:
        caps.append((60, "cap_images_missing_60"))

    if price_dec is None and km is None and not has_images:
        caps.append((50, "cap_many_missing_50"))

    cap_value: int | None = None
    caps_applied: list[str] = []
    if caps:
        cap_value = min(c[0] for c in caps)
        caps_applied = [c[1] for c in sorted(caps, key=lambda x: x[0])]

    total = raw_total
    if cap_value is not None:
        total = min(total, cap_value)

    # --- Reasons (top 3) ---
    # Lower priority number => more important.
    reasons_cand: list[tuple[int, str]] = []

    # price attractiveness
    if delta_pct is not None:
        if delta_pct < 0:
            reasons_cand.append((1, f"Preço {_fmt_pct(delta_pct)} abaixo da mediana"))
        elif delta_pct >= 0.10:
            reasons_cand.append((5, f"Preço {_fmt_pct(delta_pct)} acima da mediana"))
        else:
            reasons_cand.append((8, "Preço próximo da mediana"))
    elif price_dec is None:
        reasons_cand.append((1, "Preço ausente no anúncio"))

    # mileage
    if km_per_year is not None:
        if km_per_year >= 30000:
            reasons_cand.append((2, f"KM alto para o ano (~{km_per_year:,}/ano)".replace(",", ".")))
        elif km_per_year <= 12000:
            reasons_cand.append((7, f"KM/ano baixo (~{km_per_year:,}/ano)".replace(",", ".")))

    # Ensure stable ordering: (priority, reason)
    reasons_sorted = sorted(reasons_cand, key=lambda x: (x[0], x[1]))

    reasons: list[str] = []
    seen: set[str] = set()
    for _, r in reasons_sorted:
        if r in seen:
            continue
        reasons.append(r)
        seen.add(r)
        if len(reasons) >= 3:
            break

    return ScoreResult(
        total=int(max(0, min(100, total))),
        components=components,
        caps_applied=caps_applied,
        reasons=reasons,
        delta_vs_median_pct=delta_pct,
        market_context=market_context,
    )
