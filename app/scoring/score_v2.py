from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from app.core.text_norm import STOPWORDS as _STOPWORDS
from app.core.text_norm import expand_alphanum_pairs as _expand_alphanum_pairs
from app.core.text_norm import tokens as _tokens

from .types import MarketStats, ScoreResult

_RE_YEAR = re.compile(r"^(19\d{2}|20\d{2})$")


def _is_year_token(t: str) -> bool:
    return bool(t) and bool(_RE_YEAR.match(t))


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
    try:
        y = getattr(ad, "year", None)
        if y is not None:
            y = int(y)
            if 1900 <= y <= 2100:
                return y
    except Exception:
        pass
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
    return [t for t in _tokens(query or "") if t and t not in _STOPWORDS]


def _clamp(n: float, lo: float, hi: float) -> float:
    return lo if n < lo else hi if n > hi else n


def _fmt_pct(p: float) -> str:
    return f"{int(round(abs(p) * 100.0))}%"


def _as_decimal(v: Any) -> Decimal | None:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return v
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
    fipe_price: Decimal | None = None,
    rarity_ratio: float | None = None,
    rarity_sample_size: int | None = None,
) -> ScoreResult:
    now = now or datetime.now(timezone.utc)

    query = getattr(wishlist, "query", "") if wishlist is not None else ""
    terms = _effective_terms(query or "")
    if any(not _is_year_token(t) for t in terms):
        terms = [t for t in terms if not _is_year_token(t)]

    base = " ".join([getattr(ad, "title", "") or "", getattr(ad, "location", "") or "", getattr(ad, "make", "") or "", getattr(ad, "model", "") or ""])
    ht_list = _tokens(base)
    hay_tokens = set(ht_list)
    hay_tokens |= _expand_alphanum_pairs(ht_list)

    year = _ad_year(ad)
    if not terms:
        match_score = 35
    else:
        sat = 0
        for t in terms:
            if _is_year_token(t) and year is not None:
                sat += 1 if int(t) == int(year) else 0
            else:
                sat += 1 if t in hay_tokens else 0
        match_score = int(round(_clamp(sat / max(1, len(terms)), 0.0, 1.0) * 35.0))

    price_dec = _as_decimal(getattr(ad, "price", None))
    delta_pct: float | None = None
    market_price_score = 12
    market_context: dict[str, Any] | None = None
    if price_dec is not None and market_stats is not None and int(market_stats.sample_size or 0) >= int(min_market_sample):
        med = market_stats.median_price
        if med and med > 0:
            delta_pct = float((price_dec - med) / med)
            d = _clamp(delta_pct, -0.25, 0.25)
            market_price_score = int(round(((-d + 0.25) / 0.5) * 25.0))
            market_price_score = max(0, min(25, market_price_score))
            market_context = {"median": float(med), "p25": float(market_stats.p25_price) if market_stats.p25_price is not None else None, "p75": float(market_stats.p75_price) if market_stats.p75_price is not None else None, "sample_size": int(market_stats.sample_size or 0), "cohort": f"{market_stats.make}|{market_stats.model}|{market_stats.year}", "delta_pct": delta_pct}

    delta_vs_fipe_pct: float | None = None
    fipe_score = 5
    fipe_ctx: dict[str, Any] | None = None
    if price_dec is not None and fipe_price is not None and fipe_price > 0:
        delta_vs_fipe_pct = float((price_dec - fipe_price) / fipe_price)
        d = _clamp(delta_vs_fipe_pct, -0.25, 0.25)
        fipe_score = int(round(((-d + 0.25) / 0.5) * 10.0))
        fipe_score = max(0, min(10, fipe_score))
        fipe_ctx = {"fipe_price": float(fipe_price), "delta_vs_fipe_pct": delta_vs_fipe_pct}

    km = getattr(ad, "mileage_km", None)
    try:
        km = int(km) if km is not None else None
    except Exception:
        km = None
    mileage_score = 8
    km_per_year: int | None = None
    if km is not None and km >= 0 and year is not None and year <= now.year:
        age = max(1, now.year - year)
        km_per_year = int(round(km / age))
        if km_per_year <= 8000:
            mileage_score = 15
        elif km_per_year <= 15000:
            mileage_score = int(round(15 - (km_per_year - 8000) / 7000 * 4))
        elif km_per_year <= 25000:
            mileage_score = int(round(11 - (km_per_year - 15000) / 10000 * 6))
        elif km_per_year <= 40000:
            mileage_score = int(round(5 - (km_per_year - 25000) / 15000 * 5))
        else:
            mileage_score = 0
        mileage_score = max(0, min(15, mileage_score))

    rarity_score = 2
    if rarity_ratio is not None and int(rarity_sample_size or 0) >= int(min_market_sample):
        rarity_score = 4 if rarity_ratio <= 0.03 else 3 if rarity_ratio <= 0.06 else 2

    quality = 8
    if price_dec is None:
        quality -= 2
    if km is None:
        quality -= 2
    if not ((getattr(ad, "location", None) or "").strip() or ((getattr(ad, "city", None) or "").strip() and (getattr(ad, "state", None) or "").strip())):
        quality -= 1
    if not _ad_has_images(ad):
        quality -= 2
    if not ((getattr(ad, "url", None) or "").strip().startswith("http")):
        quality -= 1
    if not (getattr(ad, "year", None) and getattr(ad, "make", None) and getattr(ad, "model", None)):
        quality -= 2
    quality = max(0, min(10, quality))

    components = {"match": int(match_score), "market_price": int(market_price_score), "price": int(market_price_score), "fipe_price": int(fipe_score), "mileage": int(mileage_score), "rarity": int(rarity_score), "quality": int(quality)}
    raw_total = int(sum(components.values()))

    caps: list[tuple[int, str]] = []
    has_images = _ad_has_images(ad)
    if price_dec is None:
        caps.append((65, "cap_price_missing_65"))
    if not has_images:
        caps.append((60, "cap_images_missing_60"))
    if price_dec is None and km is None and not has_images:
        caps.append((50, "cap_many_missing_50"))
    cap_value = min([c[0] for c in caps], default=None)
    caps_applied = [c[1] for c in sorted(caps, key=lambda x: x[0])] if caps else []
    total = min(raw_total, cap_value) if cap_value is not None else raw_total

    reasons_cand: list[tuple[int, str]] = []
    if delta_pct is not None:
        if delta_pct < 0:
            reasons_cand.append((1, f"Preço {_fmt_pct(delta_pct)} abaixo da mediana"))
        elif delta_pct >= 0.10:
            reasons_cand.append((5, f"Preço {_fmt_pct(delta_pct)} acima da mediana"))
        else:
            reasons_cand.append((8, "Preço próximo da mediana"))
    elif price_dec is None:
        reasons_cand.append((1, "Preço ausente no anúncio"))

    if delta_vs_fipe_pct is not None:
        if delta_vs_fipe_pct < -0.08:
            reasons_cand.append((3, f"Preço {_fmt_pct(delta_vs_fipe_pct)} abaixo da FIPE"))
        elif delta_vs_fipe_pct > 0.12:
            reasons_cand.append((6, f"Preço {_fmt_pct(delta_vs_fipe_pct)} acima da FIPE"))

    if km_per_year is not None:
        if km_per_year >= 30000:
            reasons_cand.append((2, f"KM alto para o ano (~{km_per_year:,}/ano)".replace(",", ".")))
        elif km_per_year <= 12000:
            reasons_cand.append((7, f"KM/ano baixo (~{km_per_year:,}/ano)".replace(",", ".")))
    if rarity_score >= 4:
        reasons_cand.append((9, "Configuração rara no mercado"))

    reasons = []
    for _, r in sorted(reasons_cand, key=lambda x: (x[0], x[1])):
        if r not in reasons:
            reasons.append(r)
        if len(reasons) >= 3:
            break

    merged_ctx = dict(market_context or {})
    merged_ctx["fipe"] = fipe_ctx
    merged_ctx["rarity"] = {"ratio": rarity_ratio, "sample_size": rarity_sample_size}

    return ScoreResult(total=int(max(0, min(100, total))), components=components, caps_applied=caps_applied, reasons=reasons, delta_vs_median_pct=delta_pct, market_context=merged_ctx)
