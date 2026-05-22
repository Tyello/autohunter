from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from app.bot.open_ad import normalize_listing_url


@dataclass(frozen=True)
class TelegramMessagePayload:
    """Portable payload for Telegram sendMessage/sendPhoto."""

    text: str
    inline_keyboard: list[list[dict[str, str]]]

    def reply_markup_json(self) -> str:
        if not self.inline_keyboard:
            return ""
        return json.dumps({"inline_keyboard": self.inline_keyboard}, ensure_ascii=False)


@dataclass(frozen=True)
class ListingFlags:
    leilao: bool = False
    pequena_monta: bool = False
    media_monta: bool = False
    grande_monta: bool = False
    sinistro: bool = False
    recuperado: bool = False
    blindado: bool = False


_RE_WS = re.compile(r"\s+")
_MAX_LINE = 220
_MAX_REASON = 88
_MAX_FILTER_VALUE = 36
_MAX_BADGES = 8
_MAX_REASONS = 3
_NON_ACTIONABLE_REASONS = {"anuncio completo", "anúncio completo"}


def _clean(s: str | None) -> str:
    return _RE_WS.sub(" ", (s or "").strip())

def _clip(text: str | None, max_len: int) -> str:
    v = _clean(text)
    if len(v) <= max_len:
        return v
    cut = v[: max_len - 1].rstrip()
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return f"{cut}…"


def _norm_text(s: str | None) -> str:
    t = _clean(s).lower()
    t = t.replace("á", "a").replace("à", "a").replace("â", "a").replace("ã", "a")
    t = t.replace("é", "e").replace("ê", "e")
    t = t.replace("í", "i")
    t = t.replace("ó", "o").replace("ô", "o").replace("õ", "o")
    t = t.replace("ú", "u")
    t = t.replace("ç", "c")
    return t


def _format_price_brl(value: Any | None) -> str:
    if value is None:
        return "—"
    v = value
    if isinstance(v, Decimal):
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


def format_km(km: Any | None) -> str | None:
    if km is None:
        return None
    try:
        k = int(km)
        if k < 0:
            return None
    except Exception:
        return None
    return f"{k:,}".replace(",", ".")


def _short_gearbox(raw: str | None) -> str | None:
    s = _clean(raw)
    if not s:
        return None
    low = s.lower()
    if "cvt" in low:
        return "CVT"
    if "manual" in low or "mec" in low:
        return "Manual"
    if "auto" in low or "s-tronic" in low or "stronic" in low or "tiptronic" in low:
        return "Automático"
    return s[:20]


def _format_location_badge(location: str | None, *, city: str | None = None, state: str | None = None) -> str | None:
    s = _clean(location)

    m = re.search(r"([A-Za-zÀ-ÿ\s'.]+?)[,\-]\s*([A-Z]{2})\b", s)
    if m:
        city = _clean(m.group(1))
        uf = (m.group(2) or "").upper()
        if city and uf:
            return f"{city}-{uf}"
        if uf:
            return uf
    if s:
        return s[:30]

    city_clean = _clean(city)
    state_clean = _clean(state).upper()
    if city_clean and state_clean:
        return f"{city_clean}-{state_clean}"
    if state_clean:
        return state_clean
    return None




def _score_label(score_i: int) -> str | None:
    try:
        score_value = int(score_i)
    except Exception:
        return None

    if score_value >= 85:
        return "Excelente oportunidade"
    if score_value >= 70:
        return "Forte oportunidade"
    if score_value >= 50:
        return "Boa compatibilidade"
    if score_value >= 30:
        return "Compatível"
    if score_value > 0:
        return "Baixa prioridade"
    return None
def _delta_badge_text(delta_pct: float | None) -> str | None:
    if delta_pct is None:
        return None
    try:
        p = float(delta_pct)
    except Exception:
        return None
    pct_i = int(round(abs(p) * 100.0))
    if p < 0:
        return f"-{pct_i}% vs mediana"
    if p > 0:
        return f"+{pct_i}% vs mediana"
    return "0% vs mediana"


def _get_breakdown(ad: Any, score_result: Any | None) -> dict | None:
    if isinstance(score_result, dict):
        return score_result
    if score_result is not None and hasattr(score_result, "to_dict"):
        try:
            d = score_result.to_dict()
            if isinstance(d, dict):
                return d
        except Exception:
            pass

    b = getattr(ad, "score_breakdown", None)
    if isinstance(b, dict):
        return b
    if isinstance(b, str):
        try:
            d = json.loads(b)
            return d if isinstance(d, dict) else None
        except Exception:
            return None
    return None


def _parse_datetime(value: Any | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    return None


def build_recency_badge(ad: Any) -> str | None:
    extras = getattr(ad, "extras", None) or {}
    extras_dict = extras if isinstance(extras, dict) else {}

    ad_published = _parse_datetime(getattr(ad, "published_at", None))
    extras_published = _parse_datetime(extras_dict.get("published_at"))
    created_at = _parse_datetime(getattr(ad, "created_at", None))

    reliable = bool(
        extras_dict.get("published_at_reliable")
        or extras_dict.get("is_fresh_reliable")
        or extras_published
    )

    now = datetime.now(timezone.utc)

    if reliable:
        for dt in (ad_published, extras_published):
            if not dt:
                continue
            if dt > now:
                return None
            diff = now - dt
            hours = int(diff.total_seconds() // 3600)
            days = diff.days

            if hours < 1:
                return "⏱️ Agora"
            if hours < 24:
                return f"⏱️ Há {hours}h"
            if days == 1:
                return "⏱️ Ontem"
            if days <= 14:
                return f"⏱️ Há {days} dias"
            return None
        return None

    if not created_at or created_at > now:
        return None

    diff = now - created_at
    hours = diff.total_seconds() / 3600
    if hours < 2:
        return "🆕 Novo"
    if hours < 6:
        return "🕐 Recente"
    return None


def build_seller_type_badge(ad: Any) -> str | None:
    extras = getattr(ad, "extras", None) or {}
    raw = getattr(ad, "seller_type", None)
    if not raw and isinstance(extras, dict):
        raw = extras.get("seller_type") or extras.get("advertiser_type")
    text = _norm_text(str(raw or ""))
    if not text:
        return None
    if any(x in text for x in ("loj", "concessionaria", "revenda", "dealer")):
        return "🏪 Loja"
    if any(x in text for x in ("particular", "pessoa fisica", "owner")):
        return "👤 Particular"
    return None


def _join_text_sources(ad: Any) -> str:
    parts = [
        getattr(ad, "title", None),
        getattr(ad, "description", None),
    ]
    extras = getattr(ad, "extras", None) or {}
    if isinstance(extras, dict):
        for k in ("description", "observations", "notes", "details"):
            parts.append(extras.get(k))
        for v in extras.values():
            if isinstance(v, str) and len(v) > 10:
                parts.append(v)
    return " \n ".join(_clean(p) for p in parts if _clean(p))


def _has_positive_token(blob: str, token_patterns: list[str], neg_patterns: list[str]) -> bool:
    for neg in neg_patterns:
        if re.search(neg, blob):
            return False
    return any(re.search(p, blob) for p in token_patterns)


def extract_listing_flags(ad: Any) -> ListingFlags:
    blob = _norm_text(_join_text_sources(ad))

    leilao = _has_positive_token(
        blob,
        [r"\bleil[aã]o\b"],
        [r"nao\s+e\s+de\s+leil[aã]o", r"sem\s+leil[aã]o", r"nao\s+tem\s+passagem\s+de\s+leil[aã]o"],
    )
    pequena = _has_positive_token(blob, [r"pequena\s+monta"], [])
    media = _has_positive_token(blob, [r"m[eé]dia\s+monta", r"media\s+monta"], [])
    grande = _has_positive_token(blob, [r"grande\s+monta"], [])
    sinistro = _has_positive_token(blob, [r"sinistr"], [r"sem\s+sinistr", r"nao\s+(?:e|tem)\s+sinistr"])
    recuperado = _has_positive_token(blob, [r"recuperad"], [r"nao\s+recuperad", r"sem\s+recupera"])
    blindado = _has_positive_token(blob, [r"blindad", r"blindagem"], [r"nao\s+e\s+blindad", r"sem\s+blindagem"])

    return ListingFlags(
        leilao=leilao,
        pequena_monta=pequena,
        media_monta=media,
        grande_monta=grande,
        sinistro=sinistro,
        recuperado=recuperado,
        blindado=blindado,
    )


def build_title(ad: Any, *, max_len: int = 90) -> str:
    make = _clean(getattr(ad, "make", None))
    model = _clean(getattr(ad, "model", None))
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

    if make and model:
        title = f"{make} {model}"
        if year_i:
            title += f" {year_i}"
        if trim:
            title += f" {trim}"
    else:
        title = _clean(getattr(ad, "title", None) or "Novo anúncio")

    if len(title) <= max_len:
        return title
    cut = title[:max_len].rstrip()
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return f"{cut}…"


def build_badges(ad: Any, score_result: Any | None, listing_flags: ListingFlags) -> list[str]:
    badges: list[str] = []

    loc_badge = _format_location_badge(
        getattr(ad, "location", None),
        city=getattr(ad, "city", None),
        state=getattr(ad, "state", None),
    )
    if loc_badge:
        badges.append(f"📍 {loc_badge}")

    recency = build_recency_badge(ad)
    if recency:
        badges.append(recency)

    km_badge = format_km(getattr(ad, "mileage_km", None))
    if km_badge:
        badges.append(f"🛞 {km_badge} km")

    gb = _short_gearbox(getattr(ad, "transmission", None))
    if gb:
        badges.append(f"⚙️ {gb}")

    breakdown = _get_breakdown(ad, score_result) or {}
    delta_pct = breakdown.get("delta_vs_median_pct")
    if delta_pct is None:
        mc = breakdown.get("market_context") if isinstance(breakdown, dict) else None
        if isinstance(mc, dict):
            delta_pct = mc.get("delta_pct")
    dtxt = _delta_badge_text(delta_pct)
    if dtxt:
        badges.append(f"💰 {dtxt}")

    seller = build_seller_type_badge(ad)
    if seller:
        badges.append(seller)

    if listing_flags.leilao:
        badges.append("⚠️ Leilão")
    if listing_flags.pequena_monta:
        badges.append("⚠️ Pequena monta")
    if listing_flags.media_monta:
        badges.append("⚠️ Média monta")
    if listing_flags.grande_monta:
        badges.append("⚠️ Grande monta")
    if listing_flags.sinistro:
        badges.append("⚠️ Sinistro")
    if listing_flags.recuperado:
        badges.append("⚠️ Recuperado")
    if listing_flags.blindado:
        badges.append("🛡️ Blindado")

    compact: list[str] = []
    for b in badges[:_MAX_BADGES]:
        item = _clip(b, 34)
        if item:
            compact.append(item)
    return compact


def build_reasons(ad: Any, score_result: Any | None, score_i: int) -> list[str]:
    if score_i <= 0:
        return []

    breakdown = _get_breakdown(ad, score_result) or {}
    reasons = breakdown.get("reasons") or getattr(ad, "reasons", None) or []
    if isinstance(reasons, list):
        clean: list[str] = []
        seen: set[str] = set()
        for r in reasons:
            item = _clip(str(r), _MAX_REASON)
            key = _norm_text(item)
            if not item or key in seen:
                continue
            clean.append(item)
            seen.add(key)
        if clean:
            return clean[:_MAX_REASONS]

    fallback: list[str] = []
    return fallback[:3]


def _compact_filters(ad: Any) -> list[str]:
    raw = getattr(ad, "wishlist_filters", None) or []
    out: list[str] = []
    if not isinstance(raw, list):
        return out

    alias = {"price": "preço", "year": "ano", "source": "fonte", "color": "cor", "city": "cidade", "state": "estado"}
    op_map = {"eq": "=", "neq": "≠", "lte": "≤", "gte": "≥", "lt": "<", "gt": ">"}

    for f in raw[:2]:
        if not isinstance(f, dict):
            continue
        field = str(f.get("field") or "").strip().lower()
        op = str(f.get("operator") or "").strip().lower()
        value = _clip(str(f.get("value") or ""), _MAX_FILTER_VALUE)
        if not field or not op or not value:
            continue
        out.append(f"{alias.get(field, field)} {op_map.get(op, op)} {value}")
    return out


def _main_reason(reasons: list[str]) -> str | None:
    if not reasons:
        return None
    for reason in reasons:
        candidate = _clean(reason)
        if not candidate:
            continue
        if _norm_text(candidate) in _NON_ACTIONABLE_REASONS:
            continue
        return candidate
    return None


def _build_context_lines(ad: Any, main_reason: str | None, matched_filters: list[str]) -> list[str]:
    lines: list[str] = []

    if main_reason:
        lines.append(f"• Motivo principal: {main_reason}")

    for ftxt in matched_filters[:2]:
        lines.append(f"• Critério: {ftxt}")

    wishlist_query = _clip(
        getattr(ad, "wishlist_query", None)
        or getattr(ad, "query", None)
        or "",
        64,
    )
    if wishlist_query and not lines:
        lines.append(f"• Busca: {wishlist_query}")

    return lines[:3]

def build_open_button(ad: Any) -> list[list[dict[str, str]]]:
    url = normalize_listing_url(
        getattr(ad, "url", None) or "",
        source=getattr(ad, "source", None) or None,
        external_id=getattr(ad, "external_id", None) or None,
    )
    if not url:
        return []
    row = [{"text": "Abrir anúncio", "url": url}]
    nid = str(getattr(ad, "notification_id", "") or "").strip()
    if nid and getattr(ad, "reason", None) != "tracked_price_drop":
        row.append({"text": "⭐ Rastrear", "callback_data": f"TRACK:ADD:{nid}"})
    return [row]


def format_ad_message(ad: Any, score_result: Any | None = None) -> TelegramMessagePayload:
    """Central Telegram formatter used by all sources/pipelines."""

    breakdown = _get_breakdown(ad, score_result) or {}
    score = getattr(ad, "score_v2", None)
    if score is None:
        score = getattr(ad, "score", None)
    if score is None:
        score = breakdown.get("total")
    try:
        score_i = int(score) if score is not None else 0
    except Exception:
        score_i = 0

    title = build_title(ad)
    label = _score_label(score_i)
    if score_i > 0 and label:
        line1 = f"🔥 {score_i}/100 — {label} — {title}"
    elif score_i > 0:
        line1 = f"🔥 {score_i}/100 — {title}"
    else:
        line1 = title

    flags = extract_listing_flags(ad)
    badges = build_badges(ad, score_result, flags)
    line2 = " | ".join(badges) if badges else ""

    price_txt = _format_price_brl(getattr(ad, "price", None))
    source = _clean(getattr(ad, "source", None))
    line3 = f"{price_txt} • Fonte: {source}" if source else price_txt

    reasons = build_reasons(ad, score_result, score_i)
    main_reason = _main_reason(reasons)
    matched_filters = _compact_filters(ad)

    lines = [line1]
    if line2:
        lines.append(line2)
    lines.append(line3)

    context_lines = _build_context_lines(ad, main_reason, matched_filters)
    if context_lines:
        lines.append("Por que você recebeu:")
        lines.extend(context_lines)

    extra_reasons = []
    if not matched_filters:
        for r in reasons:
            clean = _clean(r)
            if not clean or clean == _clean(main_reason):
                continue
            if _norm_text(clean) in _NON_ACTIONABLE_REASONS:
                continue
            extra_reasons.append(r)
    for r in extra_reasons[:2]:
        lines.append(f"• {r}")

    compact_lines = [_clip(line, _MAX_LINE) for line in lines if _clean(line)]
    return TelegramMessagePayload(text="\n".join(compact_lines).strip(), inline_keyboard=build_open_button(ad))


def format_tracked_price_drop_message(notification: Any, ad: Any) -> TelegramMessagePayload:
    meta = getattr(notification, "score_breakdown", None) or {}
    title = _clip(build_title(ad) or "Anúncio rastreado", 90) or "Anúncio rastreado"
    current_price = meta.get("current_price")
    previous_price = meta.get("previous_price")
    drop_amount = meta.get("drop_amount")
    drop_pct = meta.get("drop_pct")
    wishlist_query = _clean(meta.get("wishlist_query")) or "sua wishlist"
    slot = meta.get("slot")

    lines = ["📉 Queda de preço no anúncio rastreado", "", title]
    if previous_price is not None:
        lines.append(f"De {_format_price_brl(previous_price)} por {_format_price_brl(current_price)}")
    else:
        lines.append(f"Preço atual: {_format_price_brl(current_price)} (queda detectada)")
    if drop_amount is not None:
        pct_txt = f" (-{str(drop_pct).replace('.', ',')}%)" if drop_pct is not None else ""
        lines.append(f"Caiu {_format_price_brl(drop_amount)}{pct_txt}")
    lines.append("")
    lines.append(f"Busca: {wishlist_query}")
    lines.append(f"Slot: {slot if slot is not None else '-'}")
    return TelegramMessagePayload(
        text="\n".join([_clip(x, _MAX_LINE) for x in lines if x is not None]).strip(),
        inline_keyboard=build_open_button(ad),
    )
