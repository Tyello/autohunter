from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional

from app.bot.open_ad import normalize_listing_url


@dataclass(frozen=True)
class TelegramMessagePayload:
    """Portable payload for Telegram sendMessage/sendPhoto.

    - text: the message body (no URL; use inline keyboard)
    - inline_keyboard: Telegram API inline keyboard structure
    """

    text: str
    inline_keyboard: list[list[dict[str, str]]]

    def reply_markup_json(self) -> str:
        if not self.inline_keyboard:
            return ""
        return json.dumps({"inline_keyboard": self.inline_keyboard}, ensure_ascii=False)


_RE_WS = re.compile(r"\s+")


def _clean(s: str) -> str:
    return _RE_WS.sub(" ", (s or "").strip())


def _format_price_brl(value: Any | None) -> str:
    if value is None:
        return "—"
    v = value
    if isinstance(v, Decimal):
        # ok
        pass
    elif isinstance(v, (int, float)):
        v = Decimal(str(v))
    else:
        try:
            v = Decimal(str(v))
        except Exception:
            return "—"

    try:
        s = f"R$ {v:,.2f}"
        return s.replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "—"


def _format_km(km: Any | None) -> str | None:
    if km is None:
        return None
    try:
        k = int(km)
        if k < 0:
            return None
    except Exception:
        return None

    # 75352 -> 75.352
    s = f"{k:,}".replace(",", ".")
    return s


def _short_gearbox(raw: str | None) -> str | None:
    s = _clean(raw or "")
    if not s:
        return None
    low = s.lower()
    if "cvt" in low:
        return "CVT"
    if "manual" in low or "mec" in low:
        return "Manual"
    if "auto" in low or "s-tronic" in low or "stronic" in low or "tiptronic" in low:
        return "Auto"
    # keep compact
    return s[:18]


def _format_location_badge(location: str | None) -> str | None:
    s = _clean(location or "")
    if not s:
        return None

    # Try "Cidade-UF" or "Cidade, UF" at end.
    m = re.search(r"([A-Za-zÀ-ÿ\s'.]+?)[,\-]\s*([A-Z]{2})\b", s)
    if m:
        city = _clean(m.group(1))
        uf = (m.group(2) or "").upper()
        if city and uf:
            return f"{city}-{uf}"
        if uf:
            return uf

    return s[:24]


def _delta_badge_text(delta_pct: float | None) -> str | None:
    if delta_pct is None:
        return None
    try:
        p = float(delta_pct)
    except Exception:
        return None

    # short, directional
    pct_i = int(round(abs(p) * 100.0))
    arrow = "↓" if p < 0 else "↑" if p > 0 else "≈"
    if arrow == "≈":
        return "≈med"
    return f"{arrow}{pct_i}% vs med"


def _get_breakdown(ad: Any) -> dict | None:
    b = getattr(ad, "score_breakdown", None)
    if b is None:
        return None
    if isinstance(b, dict):
        return b
    if isinstance(b, str):
        try:
            return json.loads(b)
        except Exception:
            return None
    return None


def format_ad_message(ad: Any) -> TelegramMessagePayload:
    """Format a normalized ad/listing into a 3-second Telegram message."""

    breakdown = _get_breakdown(ad) or {}

    # score
    score = (
        getattr(ad, "score_v2", None)
        or getattr(ad, "score", None)
        or breakdown.get("total")
        or 0
    )
    try:
        score_i = int(score)
    except Exception:
        score_i = 0

    make = _clean(getattr(ad, "make", None) or "")
    model = _clean(getattr(ad, "model", None) or "")
    year = getattr(ad, "year", None)
    try:
        year_i = int(year) if year is not None else None
    except Exception:
        year_i = None

    extras = getattr(ad, "extras", None) or {}
    trim = None
    if isinstance(extras, dict):
        trim = extras.get("trim") or extras.get("version") or extras.get("variant")
    trim = _clean(str(trim)) if trim else ""

    title_fallback = _clean(getattr(ad, "title", None) or "Novo anúncio")

    if make and model:
        head = f"{make} {model}"
        if year_i:
            head += f" {year_i}"
        if trim:
            head += f" {trim}"
    else:
        head = title_fallback

    line1 = f"🔥 {score_i}/100 — {head}".strip()

    # badges (line2)
    badges: list[str] = []

    # distance (if present) OR city/uf
    dist_km = None
    if isinstance(extras, dict):
        dist_km = extras.get("distance_km") or extras.get("distance")
    if dist_km is not None:
        try:
            d = int(float(dist_km))
            if d >= 0:
                badges.append(f"📍 {d}km")
        except Exception:
            pass
    else:
        loc_badge = _format_location_badge(getattr(ad, "location", None))
        if loc_badge:
            badges.append(f"📍 {loc_badge}")

    km_badge = _format_km(getattr(ad, "mileage_km", None))
    if km_badge:
        badges.append(f"🛞 {km_badge}km")

    gb = _short_gearbox(getattr(ad, "transmission", None))
    if gb:
        badges.append(f"⚙️ {gb}")

    # delta vs median
    # Prefer breakdown.market_context.delta_pct
    delta_pct = breakdown.get("delta_vs_median_pct")
    if delta_pct is None:
        try:
            mc = (breakdown.get("market_context") or {})
            if isinstance(mc, dict):
                delta_pct = mc.get("delta_pct")
        except Exception:
            delta_pct = None

    # If no images, omit delta badge (per spec)
    has_images = bool(getattr(ad, "thumbnail_url", None))
    if not has_images and isinstance(extras, dict):
        imgs = extras.get("images") or extras.get("image_urls")
        has_images = isinstance(imgs, (list, tuple)) and len(imgs) > 0

    if has_images:
        dtxt = _delta_badge_text(delta_pct)
        if dtxt:
            badges.append(f"💰 {dtxt}")

    line2 = " | ".join(badges)

    # line3
    price_txt = _format_price_brl(getattr(ad, "price", None))
    source = _clean(getattr(ad, "source", None) or "")
    if getattr(ad, "price", None) is None:
        line3 = f"Preço: {price_txt}"
    else:
        line3 = f"{price_txt}"
    if source:
        line3 = f"{line3} • Fonte: {source}"

    # reasons (max 3)
    reasons = breakdown.get("reasons") or getattr(ad, "reasons", None) or []
    if not isinstance(reasons, list):
        reasons = []

    reasons = [str(r) for r in reasons if str(r).strip()]
    reasons = reasons[:3]

    lines = [line1]
    if line2:
        lines.append(line2)
    lines.append(line3)
    for r in reasons:
        lines.append(f"• {r}")

    # keyboard (single button)
    url = normalize_listing_url(
        getattr(ad, "url", None) or "",
        source=getattr(ad, "source", None) or None,
        external_id=getattr(ad, "external_id", None) or None,
    )
    inline_keyboard: list[list[dict[str, str]]] = []
    if url:
        inline_keyboard = [[{"text": "Abrir anúncio", "url": url}]]

    return TelegramMessagePayload(text="\n".join(lines).strip(), inline_keyboard=inline_keyboard)
