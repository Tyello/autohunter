from __future__ import annotations

import copy
import re
import uuid
import logging
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import delete, func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.plan import Plan
from app.models.subscription import Subscription
from app.models.user import User
from app.models.wishlist import Wishlist
from app.models.wishlist_filter import WishlistFilter
from app.models.wishlist_listing_activity import WishlistListingActivity
from app.models.notification import Notification
from app.models.wishlist_token import WishlistToken
from app.models.wishlist_tracked_listing import WishlistTrackedListing
from app.services.scrape_jobs_service import enqueue_job
from app.services.source_operational_policy import (
    classify_source_operational_role,
    resolve_source_queue,
)
from app.services.system_logs_service import log
from app.services.wishlist_sources_service import allowed_sources_for_wishlists
from app.services.wishlist_tokens_service import rebuild_tokens_for_wishlist
from app.core.settings import settings
from app.core.geo import STATE_NAME_TO_UF, KNOWN_STATES_UF as KNOWN_STATES
from app.core.text_norm import normalize
from app.sources.normalize import normalize_seller_type_filter_value, normalize_body_type, normalize_doors
from app.sources.registry import get_source
from app.services.plan_capabilities import get_plan_capabilities, resolve_plan_capabilities, wishlist_limit_message


logger = logging.getLogger(__name__)
_WISHLIST_SUMMARIES_CACHE: dict[str, tuple[datetime, list[dict[str, Any]]]] = {}
_WISHLIST_SUMMARIES_CACHE_METRICS: dict[str, Any] = {
    "hits": 0,
    "misses": 0,
    "invalidations": 0,
    "global_invalidations": 0,
    "prunes": 0,
    "evictions": 0,
    "started_at": None,
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)




def _reset_wishlist_summaries_cache_metrics() -> None:
    _WISHLIST_SUMMARIES_CACHE_METRICS["hits"] = 0
    _WISHLIST_SUMMARIES_CACHE_METRICS["misses"] = 0
    _WISHLIST_SUMMARIES_CACHE_METRICS["invalidations"] = 0
    _WISHLIST_SUMMARIES_CACHE_METRICS["global_invalidations"] = 0
    _WISHLIST_SUMMARIES_CACHE_METRICS["prunes"] = 0
    _WISHLIST_SUMMARIES_CACHE_METRICS["evictions"] = 0
    _WISHLIST_SUMMARIES_CACHE_METRICS["started_at"] = _utcnow()


def reset_wishlist_summaries_cache_stats() -> None:
    _reset_wishlist_summaries_cache_metrics()


def get_wishlist_summaries_cache_stats() -> dict[str, Any]:
    now = _utcnow()
    ttl_seconds = int(getattr(settings, "wishlist_summaries_cache_ttl_seconds", 0) or 0)
    max_entries = int(getattr(settings, "wishlist_summaries_cache_max_entries", 0) or 0)
    entries = list(_WISHLIST_SUMMARIES_CACHE.values())
    ages = [max(0.0, (now - ts).total_seconds()) for ts, _ in entries]
    hits = int(_WISHLIST_SUMMARIES_CACHE_METRICS.get("hits") or 0)
    misses = int(_WISHLIST_SUMMARIES_CACHE_METRICS.get("misses") or 0)
    total = hits + misses
    started_at = _WISHLIST_SUMMARIES_CACHE_METRICS.get("started_at")
    return {
        "cache_enabled": ttl_seconds > 0,
        "ttl_seconds": ttl_seconds,
        "max_entries": max_entries,
        "size": len(_WISHLIST_SUMMARIES_CACHE),
        "hits": hits,
        "misses": misses,
        "invalidations": int(_WISHLIST_SUMMARIES_CACHE_METRICS.get("invalidations") or 0),
        "global_invalidations": int(_WISHLIST_SUMMARIES_CACHE_METRICS.get("global_invalidations") or 0),
        "prunes": int(_WISHLIST_SUMMARIES_CACHE_METRICS.get("prunes") or 0),
        "evictions": int(_WISHLIST_SUMMARIES_CACHE_METRICS.get("evictions") or 0),
        "hit_rate_pct": round((hits / total) * 100.0, 2) if total > 0 else 0.0,
        "oldest_entry_age_seconds": max(ages) if ages else None,
        "newest_entry_age_seconds": min(ages) if ages else None,
        "started_at": started_at.isoformat() if isinstance(started_at, datetime) else None,
        "since_seconds": max(0.0, (now - started_at).total_seconds()) if isinstance(started_at, datetime) else None,
    }


_reset_wishlist_summaries_cache_metrics()
def invalidate_wishlist_summaries_cache(user_id=None) -> None:
    if user_id is None:
        _WISHLIST_SUMMARIES_CACHE.clear()
        _WISHLIST_SUMMARIES_CACHE_METRICS["global_invalidations"] += 1
        return
    removed = _WISHLIST_SUMMARIES_CACHE.pop(str(user_id), None)
    if removed is not None:
        _WISHLIST_SUMMARIES_CACHE_METRICS["invalidations"] += 1


def _prune_wishlist_summaries_cache(now: datetime, ttl_seconds: int, max_entries: int) -> None:
    if ttl_seconds > 0:
        expired_keys = [k for k, (ts, _) in _WISHLIST_SUMMARIES_CACHE.items() if (now - ts).total_seconds() > ttl_seconds]
        for key in expired_keys:
            _WISHLIST_SUMMARIES_CACHE.pop(key, None)
        if expired_keys:
            _WISHLIST_SUMMARIES_CACHE_METRICS["prunes"] += len(expired_keys)
    if max_entries <= 0:
        evicted = len(_WISHLIST_SUMMARIES_CACHE)
        _WISHLIST_SUMMARIES_CACHE.clear()
        if evicted:
            _WISHLIST_SUMMARIES_CACHE_METRICS["evictions"] += evicted
        return
    while len(_WISHLIST_SUMMARIES_CACHE) > max_entries:
        oldest_key = min(_WISHLIST_SUMMARIES_CACHE.items(), key=lambda item: item[1][0])[0]
        _WISHLIST_SUMMARIES_CACHE.pop(oldest_key, None)
        _WISHLIST_SUMMARIES_CACHE_METRICS["evictions"] += 1

# Fallback (quando não existir plano/assinatura no banco ainda)
DEFAULT_MAX_WISHLISTS_PER_USER = 2

# Fontes conhecidas hoje (expanda sem medo)
# Aceita:
#  - "até 2004" / "ate 2004" / "ano<=2004"
#  - "a partir de 2014" / "ano>=2014"
#  - "entre 2014 e 2020" / "2014 até 2020" / "2014-2020"
_FULL_YEAR_TOKEN = r"(?<!\d)((?:19|20)\d{2})(?!\d)"

_YEAR_MAX_PATTERNS = [
    re.compile(rf"(?:\bate\b|\baté\b)\s+{_FULL_YEAR_TOKEN}", re.IGNORECASE),
    re.compile(rf"(?:\bate\b|\baté\b)\s+ano\s+{_FULL_YEAR_TOKEN}", re.IGNORECASE),
    re.compile(rf"\bano\s*(?:<=|=<|≤)\s*{_FULL_YEAR_TOKEN}", re.IGNORECASE),
    re.compile(rf"\byear\s*(?:<=|=<|≤)\s*{_FULL_YEAR_TOKEN}", re.IGNORECASE),
]

_YEAR_MIN_PATTERNS = [
    re.compile(rf"\b(?:a\s+partir\s+de|apartir\s+de|desde)\s+{_FULL_YEAR_TOKEN}", re.IGNORECASE),
    re.compile(rf"\bano\s*(?:>=|=>|≥)\s*{_FULL_YEAR_TOKEN}", re.IGNORECASE),
    re.compile(rf"\byear\s*(?:>=|=>|≥)\s*{_FULL_YEAR_TOKEN}", re.IGNORECASE),
]

_YEAR_RANGE_PATTERNS = [
    re.compile(rf"\bentre\s+{_FULL_YEAR_TOKEN}\s+e\s+{_FULL_YEAR_TOKEN}\b", re.IGNORECASE),
    re.compile(rf"\bde\s+{_FULL_YEAR_TOKEN}\s+a\s+{_FULL_YEAR_TOKEN}\b", re.IGNORECASE),
    re.compile(rf"\b{_FULL_YEAR_TOKEN}\s*(?:\bate\b|\baté\b)\s*{_FULL_YEAR_TOKEN}\b", re.IGNORECASE),
    re.compile(rf"\b{_FULL_YEAR_TOKEN}\s*(?:-|–|—)\s*{_FULL_YEAR_TOKEN}\b", re.IGNORECASE),
]
_YEAR_STANDALONE_PATTERN = re.compile(r"(?:\bano\s+)?(\d{4})\b$", re.IGNORECASE)


# Aceita diretivas de preço (BRL) embutidas na query:
#  - "entre 200k e 300k" / "200k-300k" / "de R$ 80.000 a R$ 120.000"
#  - "a partir de 80k" / "até 120k"
#  - "preço<=120k" / "valor >= 100000"
_PRICE_RANGE_PATTERNS = [
    re.compile(
        r"\bentre\s+(?:r\$\s*)?([0-9\.,]+\s*[kKmM]?)\s+e\s+(?:r\$\s*)?([0-9\.,]+\s*[kKmM]?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bde\s+(?:r\$\s*)?([0-9\.,]+\s*[kKmM]?)\s+a\s+(?:r\$\s*)?([0-9\.,]+\s*[kKmM]?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b([0-9\.,]+\s*[kKmM]?)\s*(?:-|–|—)\s*([0-9\.,]+\s*[kKmM]?)\b",
        re.IGNORECASE,
    ),
]

_PRICE_MAX_PATTERNS = [
    re.compile(
        r"\b(?:ate|até)\s+(?:r\$\s*)?([0-9\.,]+\s*[kKmM]?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:preco|preço|valor|price)\s*(?:<=|=<|≤)\s*(?:r\$\s*)?([0-9\.,]+\s*[kKmM]?)\b",
        re.IGNORECASE,
    ),
]

_PRICE_MIN_PATTERNS = [
    re.compile(
        r"\b(?:a\s+partir\s+de|apartir\s+de|desde)\s+(?:r\$\s*)?([0-9\.,]+\s*[kKmM]?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:preco|preço|valor|price)\s*(?:>=|=>|≥)\s*(?:r\$\s*)?([0-9\.,]+\s*[kKmM]?)\b",
        re.IGNORECASE,
    ),
]




def _known_sources() -> set[str]:
    from app.sources import list_sources
    try:
        return {p.name.lower() for p in list_sources()}
    except Exception:
        return set()

def _parse_human_money_to_int(raw: str) -> Optional[int]:
    """Converte valores do tipo '200k', '1.2m', '120.000', 'R$ 80.000' em inteiro (centavos ignorados)."""
    if not raw:
        return None

    s = raw.strip().lower()
    s = s.replace("r$", "").strip()
    s = re.sub(r"\s+", "", s)

    mult = 1
    if s.endswith("k"):
        mult = 1_000
        s = s[:-1]
    elif s.endswith("m"):
        mult = 1_000_000
        s = s[:-1]

    s = s.replace(".", "") if re.search(r"\d\.\d{3}", s) else s
    s = s.replace(",", ".")
    s = re.sub(r"[^0-9\.]+", "", s)
    if not s:
        return None

    try:
        num = float(s)
    except Exception:
        return None

    if num <= 0:
        return None

    val = int(round(num * mult))
    return val if val > 0 else None


def _is_plausible_price(v: int) -> bool:
    return 1 <= v <= 9_999_999_999


def _clean_span(q: str, start: int, end: int) -> str:
    q = (q[:start] + " " + q[end:]).strip()
    q = re.sub(r"\s+", " ", q).strip()
    return q


def _extract_price_directives(query: str) -> Tuple[str, Optional[int], Optional[int]]:
    q = (query or "").strip()
    if not q:
        return q, None, None

    pmin: Optional[int] = None
    pmax: Optional[int] = None

    for rx in _PRICE_RANGE_PATTERNS:
        m = rx.search(q)
        if not m:
            continue

        v1 = _parse_human_money_to_int(m.group(1) or "")
        v2 = _parse_human_money_to_int(m.group(2) or "")
        if not v1 or not v2:
            continue
        if not (_is_plausible_price(v1) and _is_plausible_price(v2)):
            continue

        pmin, pmax = (v1, v2) if v1 <= v2 else (v2, v1)
        q = _clean_span(q, m.start(), m.end())
        break

    if pmax is None:
        for rx in _PRICE_MAX_PATTERNS:
            m = rx.search(q)
            if not m:
                continue
            raw = (m.group(1) or "").strip()
            v = _parse_human_money_to_int(raw)

            # evita confundir "até 2020" com preço
            if v is None and raw.isdigit() and len(raw) == 4:
                continue

            if v and _is_plausible_price(v):
                pmax = v
                q = _clean_span(q, m.start(), m.end())
                break

    if pmin is None:
        for rx in _PRICE_MIN_PATTERNS:
            m = rx.search(q)
            if not m:
                continue
            raw = (m.group(1) or "").strip()
            v = _parse_human_money_to_int(raw)
            if v and _is_plausible_price(v):
                pmin = v
                q = _clean_span(q, m.start(), m.end())
                break

    return q, pmin, pmax


def _extract_year_directives(query: str) -> Tuple[str, Optional[int], Optional[int]]:
    """Extrai diretivas de ano (min/max/range) e limpa a query.

    **Contrato importante:**
    - "entre 2014 e 2015" => year_min=2014, year_max=2015 (INCLUSIVO)
    - "até 2015" => year_max=2015 (INCLUSIVO)
    - "a partir de 2014" => year_min=2014 (INCLUSIVO)
    """
    q = (query or "").strip()
    if not q:
        return q, None, None

    year_min: Optional[int] = None
    year_max: Optional[int] = None

    for rx in _YEAR_RANGE_PATTERNS:
        m = rx.search(q)
        if not m:
            continue
        try:
            y1 = int(m.group(1))
            y2 = int(m.group(2))
        except Exception:
            y1 = y2 = None
        if y1 and y2 and 1900 <= y1 <= 2100 and 1900 <= y2 <= 2100:
            year_min, year_max = (y1, y2) if y1 <= y2 else (y2, y1)
            q = _clean_span(q, m.start(), m.end())
            break

    if year_max is None:
        for rx in _YEAR_MAX_PATTERNS:
            m = rx.search(q)
            if not m:
                continue
            try:
                y = int(m.group(1))
            except Exception:
                y = None
            if y and 1900 <= y <= 2100:
                year_max = y
                q = _clean_span(q, m.start(), m.end())
                break

    if year_min is None:
        for rx in _YEAR_MIN_PATTERNS:
            m = rx.search(q)
            if not m:
                continue
            try:
                y = int(m.group(1))
            except Exception:
                y = None
            if y and 1900 <= y <= 2100:
                year_min = y
                q = _clean_span(q, m.start(), m.end())
                break

    if year_min is None and year_max is None:
        m = _YEAR_STANDALONE_PATTERN.search(q)
        if m:
            try:
                y = int(m.group(1))
            except Exception:
                y = None
            if y and 1900 <= y <= 2100:
                year_min = y
                year_max = y
                q = _clean_span(q, m.start(), m.end())

    return q, year_min, year_max


def numeric_filter_match(value: Optional[int], operator: str, target: Optional[int]) -> bool:
    """Comparação numérica padronizada para filtros.

    Esse helper existe pra **evitar o bug clássico** do intervalo ficar exclusivo:
    - gte/lte são INCLUSIVOS.
    - gt/lt são EXCLUSIVOS.
    - eq/neq são óbvios.

    Se value ou target forem None, falha (retorna False).
    """
    if value is None or target is None:
        return False

    op = (operator or "").strip().lower()
    if op == "gte":
        return value >= target
    if op == "lte":
        return value <= target
    if op == "gt":
        return value > target
    if op == "lt":
        return value < target
    if op == "eq":
        return value == target
    if op == "neq":
        return value != target

    return False


def year_in_directive_range(year: Optional[int], year_min: Optional[int], year_max: Optional[int]) -> bool:
    """Valida um ano contra as diretivas extraídas.

    **INCLUSIVO nas bordas**:
      - year_min => year >= year_min
      - year_max => year <= year_max
    """
    if year is None:
        return False

    if year_min is not None and not numeric_filter_match(year, "gte", year_min):
        return False
    if year_max is not None and not numeric_filter_match(year, "lte", year_max):
        return False
    return True


def _as_utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def get_user_plan_snapshot(db: Session, user_id) -> Dict[str, Any]:
    free_caps = get_plan_capabilities("free")
    snap: Dict[str, Any] = {
        "plan_code": free_caps.plan_code,
        "max_wishlists": free_caps.max_active_wishlists,
        "daily_alert_limit": free_caps.daily_notifications_per_wishlist,
        "daily_notifications_per_wishlist": free_caps.daily_notifications_per_wishlist,
    }

    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return snap

        q = db.query(Subscription)

        if hasattr(Subscription, "account_id") and getattr(user, "account_id", None) is not None:
            q = q.filter(Subscription.account_id == user.account_id)
        elif hasattr(Subscription, "user_id"):
            q = q.filter(Subscription.user_id == user_id)
        else:
            return snap

        if hasattr(Subscription, "status"):
            q = q.filter(Subscription.status == "active")
        elif hasattr(Subscription, "is_active"):
            q = q.filter(Subscription.is_active.is_(True))

        if hasattr(Subscription, "created_at"):
            q = q.order_by(Subscription.created_at.desc())
        else:
            q = q.order_by(Subscription.id.desc())

        sub = q.first()
        if not sub:
            return snap
        now = datetime.now(timezone.utc)
        current_period_end = _as_utc_datetime(getattr(sub, "current_period_end", None))
        ends_at = _as_utc_datetime(getattr(sub, "ends_at", None))
        effective_end = current_period_end or ends_at
        if effective_end and effective_end <= now:
            return snap

        plan = db.query(Plan).filter(Plan.id == sub.plan_id).first() if getattr(sub, "plan_id", None) else None
        if not plan:
            return snap

        snap["plan_code"] = getattr(plan, "code", "free") or "free"
        caps = resolve_plan_capabilities(db, snap["plan_code"])
        snap["plan_code"] = caps.plan_code
        snap["max_wishlists"] = caps.max_active_wishlists
        snap["daily_notifications_per_wishlist"] = caps.daily_notifications_per_wishlist
        snap["daily_alert_limit"] = caps.daily_notifications_per_wishlist
        if effective_end:
            snap["current_period_end"] = effective_end

        return snap

    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        return snap


def get_max_wishlists_for_user(db: Session, user_id) -> int:
    snap = get_user_plan_snapshot(db, user_id)
    return int(snap.get("max_wishlists") or DEFAULT_MAX_WISHLISTS_PER_USER)


def list_wishlists(db: Session, user_id):
    return (
        db.query(Wishlist)
        .filter(Wishlist.user_id == user_id)
        .filter(Wishlist.deleted_at.is_(None))
        .order_by(Wishlist.created_at.asc())
        .all()
    )




def _compute_wishlist_summaries(db: Session, user_id) -> list[dict[str, Any]]:
    wishlists = list_wishlists(db, user_id)
    if not wishlists:
        return []
    wishlist_ids = [w.id for w in wishlists]
    filter_counts = {
        wishlist_id: count
        for wishlist_id, count in (
            db.query(WishlistFilter.wishlist_id, func.count(WishlistFilter.id))
            .filter(WishlistFilter.wishlist_id.in_(wishlist_ids))
            .filter(WishlistFilter.is_active.is_(True))
            .group_by(WishlistFilter.wishlist_id)
            .all()
        )
    }
    filters_by_wishlist: dict[Any, list[dict[str, str]]] = defaultdict(list)
    for row in (
        db.query(WishlistFilter.wishlist_id, WishlistFilter.field, WishlistFilter.operator, WishlistFilter.value)
        .filter(WishlistFilter.wishlist_id.in_(wishlist_ids))
        .filter(WishlistFilter.is_active.is_(True))
        .order_by(WishlistFilter.created_at.asc())
        .all()
    ):
        filters_by_wishlist[row.wishlist_id].append(
            {"field": row.field, "operator": row.operator, "value": row.value}
        )
    tracked_counts = {
        wishlist_id: count
        for wishlist_id, count in (
            db.query(WishlistTrackedListing.wishlist_id, func.count(WishlistTrackedListing.id))
            .filter(WishlistTrackedListing.wishlist_id.in_(wishlist_ids))
            .filter(WishlistTrackedListing.is_active.is_(True))
            .group_by(WishlistTrackedListing.wishlist_id)
            .all()
        )
    }
    window_start = _utcnow() - timedelta(hours=24)
    notifications_24h_counts = {
        wishlist_id: count
        for wishlist_id, count in (
            db.query(Notification.wishlist_id, func.count(Notification.id))
            .filter(Notification.wishlist_id.in_(wishlist_ids))
            .filter(Notification.status == "sent")
            .filter(Notification.sent_at.isnot(None))
            .filter(Notification.sent_at >= window_start)
            .group_by(Notification.wishlist_id)
            .all()
        )
    }
    out = []
    for i, wl in enumerate(wishlists, start=1):
        out.append({
            "index": i,
            "wishlist_id": wl.id,
            "query": wl.query,
            "is_active": bool(getattr(wl, "is_active", True)),
            "include_auctions": bool(getattr(wl, "include_auctions", False)),
            "filters_count": int(filter_counts.get(wl.id, 0) or 0),
            "filters": filters_by_wishlist.get(wl.id, []),
            "tracked_count": int(tracked_counts.get(wl.id, 0) or 0),
            "tracked_limit": 3,
            "notifications_24h_count": int(notifications_24h_counts.get(wl.id, 0) or 0),
        })
    return out


def get_wishlist_summaries(db: Session, user_id):
    """Return lightweight operational summary for each user wishlist.

    v2 keeps low-cost signals only (filters + tracked slots + active flag + notifications sent 24h).
    notifications_24h_count can be stale for up to TTL seconds to avoid menu-driven query bursts.
    """
    ttl_seconds = int(getattr(settings, "wishlist_summaries_cache_ttl_seconds", 0) or 0)
    max_entries = int(getattr(settings, "wishlist_summaries_cache_max_entries", 0) or 0)
    cache_key = str(user_id)
    now = _utcnow()
    if ttl_seconds <= 0:
        return _compute_wishlist_summaries(db, user_id)
    cached = _WISHLIST_SUMMARIES_CACHE.get(cache_key)
    if cached:
        ts, payload = cached
        if (now - ts).total_seconds() <= ttl_seconds:
            _WISHLIST_SUMMARIES_CACHE_METRICS["hits"] += 1
            return copy.deepcopy(payload)
        removed = _WISHLIST_SUMMARIES_CACHE.pop(cache_key, None)
        if removed is not None:
            _WISHLIST_SUMMARIES_CACHE_METRICS["prunes"] += 1
    _WISHLIST_SUMMARIES_CACHE_METRICS["misses"] += 1
    computed = _compute_wishlist_summaries(db, user_id)
    _WISHLIST_SUMMARIES_CACHE[cache_key] = (now, computed)
    _prune_wishlist_summaries_cache(now, ttl_seconds, max_entries)
    return copy.deepcopy(computed)


def set_wishlist_active_state(db: Session, user_id, wishlist_index: int, is_active: bool) -> tuple[bool, str]:
    wishlists = list_wishlists(db, user_id)
    if wishlist_index < 1 or wishlist_index > len(wishlists):
        return False, "Busca não encontrada para sua conta."
    wl = wishlists[wishlist_index - 1]
    wl.is_active = bool(is_active)
    db.add(wl)
    db.commit()
    invalidate_wishlist_summaries_cache(user_id)
    return True, wl.query

def add_wishlist(db: Session, user_id, query: str, enqueue_initial_run: bool = True, include_auctions: bool = False):
    """Cria wishlist e opcionalmente cria filtros de ano/preço se diretivas existirem."""
    try:
        db.rollback()
    except Exception:
        pass

    max_wishlists = get_max_wishlists_for_user(db, user_id)
    count = (
        db.query(func.count(Wishlist.id))
        .filter(Wishlist.user_id == user_id)
        .filter(Wishlist.deleted_at.is_(None))
        .scalar()
        or 0
    )
    if count >= max_wishlists:
        return False, wishlist_limit_message(max_wishlists)

    cleaned_query, year_min, year_max = _extract_year_directives(query)
    cleaned_query, price_min, price_max = _extract_price_directives(cleaned_query)

    cleaned_query = (cleaned_query or "").strip()
    if not cleaned_query:
        return False, "Query inválida. Ex: /wishlist_add audi a6 entre 2014 e 2020"
    if cleaned_query.lower() in {"gte", "lte", "gt", "lt", "eq", "neq"}:
        return False, "Query inválida. Use um termo de busca (ex: civic touring)."

    w = Wishlist(
        id=uuid.uuid4(),
        user_id=user_id,
        query=cleaned_query,
        is_active=True,
        include_auctions=bool(include_auctions),
    )
    db.add(w)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return False, "Erro ao salvar wishlist (conflito/duplicidade)."
    except SQLAlchemyError:
        db.rollback()
        return False, "Erro ao salvar wishlist. Tente novamente."
    invalidate_wishlist_summaries_cache(user_id)

    filters = []
    # IMPORTANTE: year range é INCLUSIVO => gte/lte
    if year_min:
        filters.append(WishlistFilter(wishlist_id=w.id, field="year", operator="gte", value=str(year_min)))
    if year_max:
        filters.append(WishlistFilter(wishlist_id=w.id, field="year", operator="lte", value=str(year_max)))

    if price_min:
        filters.append(WishlistFilter(wishlist_id=w.id, field="price", operator="gte", value=str(price_min)))
    if price_max:
        filters.append(WishlistFilter(wishlist_id=w.id, field="price", operator="lte", value=str(price_max)))

    if filters:
        db.add_all(filters)
        try:
            db.commit()
        except Exception:
            db.rollback()

    # build token index for scalable matching
    try:
        rebuild_tokens_for_wishlist(db, w)
        db.commit()
    except Exception:
        db.rollback()

    if not enqueue_initial_run:
        invalidate_wishlist_summaries_cache(user_id)
        return True, (
            f"✅ Wishlist criada: {cleaned_query}\n\n"
            "Monitoramento salvo. A primeira busca será disparada quando o fluxo guiado concluir os filtros."
        )

    run_summary = trigger_initial_run_for_wishlist(db, w, run_reason="wishlist_created")
    invalidate_wishlist_summaries_cache(user_id)

    if run_summary.get("failed", 0) > 0 and run_summary.get("triggered", 0) == 0:
        return True, "✅ Busca criada com sucesso.\nNão consegui agendar a primeira busca agora, mas o monitoramento contínuo segue ativo."
    return True, (
        f"✅ Wishlist criada: {cleaned_query}\n\n"
        "Vou fazer a primeira busca em segundo plano.\n"
        "Você será avisado se encontrar bons anúncios."
    )


@dataclass(frozen=True)
class NormalizedWishlistFilter:
    field: str
    operator: str
    value: str

@dataclass(frozen=True)
class ParsedWishlistDraft:
    cleaned_query: str
    filters: list[NormalizedWishlistFilter]

@dataclass(frozen=True)
class WishlistCreateResult:
    ok: bool
    message: str
    wishlist_id: Optional[uuid.UUID] = None
    initial_run_summary: Optional[dict[str, Any]] = None


def parse_wishlist_filter_expression(field: str, raw_text: str) -> list[NormalizedWishlistFilter]:
    canonical_field = {
        "km": "mileage_km",
        "kms": "mileage_km",
        "quilometragem": "mileage_km",
        "mileage": "mileage_km",
        "mileage_km": "mileage_km",
    }.get((field or "").strip().lower(), (field or "").strip().lower())
    text = (raw_text or "").strip()
    if not text:
        raise ValueError("Valor inválido.")

    if canonical_field in {"price", "year", "mileage_km"}:
        lowered = text.lower()
        range_match = re.search(r"\bentre\s+([0-9\.\,]+)\s+e\s+([0-9\.\,]+)", lowered)
        if range_match:
            lo = normalize_wishlist_filter_input(canonical_field, "gte", range_match.group(1)).value
            hi = normalize_wishlist_filter_input(canonical_field, "lte", range_match.group(2)).value
            lo_i, hi_i = sorted((int(lo), int(hi)))
            return [
                normalize_wishlist_filter_input(canonical_field, "gte", str(lo_i)),
                normalize_wishlist_filter_input(canonical_field, "lte", str(hi_i)),
            ]
        if any(term in lowered for term in ("a partir de", "desde", "acima de", "mais de")):
            num = re.search(r"([0-9\.\,]+)", lowered)
            if not num:
                raise ValueError("Valor inválido.")
            return [normalize_wishlist_filter_input(canonical_field, "gte", num.group(1))]
        if "maior que" in lowered:
            num = re.search(r"([0-9\.\,]+)", lowered)
            if not num:
                raise ValueError("Valor inválido.")
            return [normalize_wishlist_filter_input(canonical_field, "gt", num.group(1))]
        if "menor que" in lowered:
            num = re.search(r"([0-9\.\,]+)", lowered)
            if not num:
                raise ValueError("Valor inválido.")
            return [normalize_wishlist_filter_input(canonical_field, "lt", num.group(1))]
        if "até" in lowered or "ate" in lowered:
            num = re.search(r"([0-9\.\,]+)", lowered)
            if not num:
                raise ValueError("Valor inválido.")
            return [normalize_wishlist_filter_input(canonical_field, "lte", num.group(1))]
        num = re.search(r"([0-9\.\,]+)", lowered)
        if not num:
            raise ValueError("Valor inválido.")
        default_op = "gte" if canonical_field == "year" else "lte"
        return [normalize_wishlist_filter_input(canonical_field, default_op, num.group(1))]

    return [normalize_wishlist_filter_input(canonical_field, "eq", text)]


def parse_wishlist_query_with_implicit_filters(query: str) -> ParsedWishlistDraft:
    original = (query or "").strip()
    cleaned, year_min, year_max = _extract_year_directives(original)
    cleaned, price_min, price_max = _extract_price_directives(cleaned)
    filters: list[NormalizedWishlistFilter] = []
    if year_min is not None:
        filters.append(NormalizedWishlistFilter("year", "gte", str(year_min)))
    if year_max is not None:
        filters.append(NormalizedWishlistFilter("year", "lte", str(year_max)))
    if price_min is not None:
        filters.append(NormalizedWishlistFilter("price", "gte", str(price_min)))
    if price_max is not None:
        filters.append(NormalizedWishlistFilter("price", "lte", str(price_max)))
    cleaned_query = (cleaned or "").strip()
    return ParsedWishlistDraft(cleaned_query=cleaned_query or original, filters=filters)

def normalize_wishlist_filter_input(field: str, operator: str, value: str) -> NormalizedWishlistFilter:
    field = (field or "").strip().lower()
    operator = (operator or "").strip().lower()
    value = (value or "").strip()

    field_aliases = {
        "km": "mileage_km", "kms": "mileage_km", "quilometragem": "mileage_km", "kilometragem": "mileage_km",
        "mileage": "mileage_km", "mileage_km": "mileage_km", "seller": "seller_type", "vendedor": "seller_type",
        "tipo_vendedor": "seller_type", "tipo_de_vendedor": "seller_type", "anunciante": "seller_type", "loja": "seller_type",
        "particular": "seller_type", "concessionaria": "seller_type", "concessionária": "seller_type", "revenda": "seller_type",
        "seller_type": "seller_type", "cor": "color", "color": "color", "colour": "color",
        "cidade": "city", "city": "city", "municipio": "city", "município": "city",
        "estado": "state", "uf": "state", "state": "state",
        "carroceria": "body_type", "tipo_carroceria": "body_type",
        "tipo_de_carroceria": "body_type", "categoria": "body_type", "tipo": "body_type", "body": "body_type",
        "body_type": "body_type", "estilo": "body_type", "porta": "doors", "portas": "doors", "qtd_portas": "doors",
        "quantidade_portas": "doors", "quantidade_de_portas": "doors", "doors": "doors",
    }
    field = field_aliases.get(field, field)

    op_aliases = {"<=": "lte", "=<": "lte", "até": "lte", "ate": "lte", "max": "lte", "máximo": "lte", "maximo": "lte",
                  ">=": "gte", "=>": "gte", "mínimo": "gte", "minimo": "gte", "min": "gte", "between": "between",
                  "entre": "between", "igual": "eq", "equals": "eq", "=": "eq", "apenas": "eq", "somente": "eq", "excluir": "neq",
                  "diferente": "neq", "!=": "neq"}
    operator = op_aliases.get(operator, operator)

    if field not in ("price", "source", "year", "color", "city", "state", "mileage_km", "seller_type", "body_type", "doors"):
        raise ValueError("Campo inválido. Use: price | year | mileage_km | source | color | city | state | seller_type | body_type | doors")
    if field in ("price", "year", "mileage_km", "doors") and operator not in ("lt", "lte", "gt", "gte", "eq", "neq", "between"):
        raise ValueError(f"Operador inválido para {field}. Use: lt|lte|gt|gte|eq|neq|between")
    if field == "source" and operator not in ("eq", "neq"):
        raise ValueError("Operador inválido para source. Use: eq|neq")
    if field in ("color", "city", "seller_type", "body_type") and operator not in ("eq", "neq"):
        raise ValueError(f"Operador inválido para {field}. Use: eq|neq")
    if field == "state" and operator != "eq":
        raise ValueError("Operador inválido para state. Use: eq")

    if field == "source":
        v = value.strip().lower()
        if v not in _known_sources():
            raise ValueError("Valor inválido para source. Use: " + " | ".join(sorted(_known_sources())))
        value = v
    if field == "year":
        try:
            y = int(value)
        except Exception:
            raise ValueError("Ano inválido. Ex: year lte 2005")
        if y < 1900 or y > 2100:
            raise ValueError("Ano fora do intervalo (1900-2100).")
        value = str(y)
    if field == "mileage_km":
        if operator == "between":
            parts = value.split()
            if len(parts) != 2:
                raise ValueError("Quilometragem inválida. Ex: mileage_km between 30000 90000")
            bounds: list[int] = []
            for p in parts:
                raw = p.lower().replace("km", "").replace(".", "").replace(",", "").strip()
                try:
                    km = int(raw)
                except Exception:
                    raise ValueError("Quilometragem inválida. Ex: mileage_km between 30000 90000")
                if km < 0 or km > 1_500_000:
                    raise ValueError("Quilometragem fora do intervalo (0-1500000).")
                bounds.append(km)
            lo, hi = sorted(bounds)
            value = f"{lo},{hi}"
        else:
            raw = value.lower().replace("km", "").replace(".", "").replace(",", "").strip()
            try:
                km = int(raw)
            except Exception:
                raise ValueError("Quilometragem inválida. Ex: mileage_km lte 90000")
            if km < 0 or km > 1_500_000:
                raise ValueError("Quilometragem fora do intervalo (0-1500000).")
            value = str(km)
    if field == "price":
        if operator == "between":
            parts = value.split()
            if len(parts) != 2:
                raise ValueError("Preço inválido. Ex: price between 70000 90000")
            bounds: list[int] = []
            for p in parts:
                parsed = _parse_human_money_to_int(p)
                if parsed is None:
                    raise ValueError("Preço inválido. Ex: price between 70000 90000")
                bounds.append(parsed)
            lo, hi = sorted(bounds)
            value = f"{lo},{hi}"
            return NormalizedWishlistFilter(field=field, operator=operator, value=value)
        raw = value.lower().replace("r$", "").replace("km", "").strip()
        raw = re.sub(r"^(até|ate|menor que|maior que|a partir de)\s+", "", raw).strip()
        parsed = _parse_human_money_to_int(raw)
        if parsed is None:
            raise ValueError("Preço inválido. Ex: 150000 ou 150.000")
        value = str(parsed)
    if field == "doors":
        if operator == "between":
            parts = value.split()
            if len(parts) != 2:
                raise ValueError("Portas inválido. Ex: doors between 2 4")
            bounds: list[int] = []
            for p in parts:
                d = normalize_doors(p)
                if d is None:
                    raise ValueError("Portas inválido. Use um número inteiro entre 1 e 6.")
                bounds.append(d)
            lo, hi = sorted(bounds)
            value = f"{lo},{hi}"
        else:
            doors = normalize_doors(value)
            if doors is None:
                raise ValueError("Portas inválido. Use um número inteiro entre 1 e 6.")
            value = str(doors)
    if field in ("color", "city"):
        if len(value.strip()) < 2:
            if field == "city":
                raise ValueError("Para cidade, use o nome da cidade. Exemplo: São Paulo.")
            raise ValueError("Para cor, use uma cor. Exemplo: vermelho.")
        value = normalize(value).strip()
    if field == "state":
        raw_state = value.strip()
        uf = raw_state.upper()
        if uf not in KNOWN_STATES:
            normalized = raw_state.lower().replace("á", "a").replace("à", "a").replace("â", "a").replace("ã", "a").replace("é", "e").replace("ê", "e").replace("í", "i").replace("ó", "o").replace("ô", "o").replace("õ", "o").replace("ú", "u").replace("ç", "c")
            uf = STATE_NAME_TO_UF.get(normalized, "")
        if uf not in KNOWN_STATES:
            raise ValueError("Para estado, use uma UF com 2 letras. Exemplo: SP.")
        value = uf
    if field == "seller_type":
        normalized_seller = normalize_seller_type_filter_value(value)
        if not normalized_seller:
            raise ValueError("Valor inválido para seller_type. Use: particular | loja | revenda | concessionária")
        value = normalized_seller
    if field == "body_type":
        normalized_body_type = normalize_body_type(value)
        if not normalized_body_type:
            raise ValueError("Valor inválido para body_type. Use: hatch | sedan | suv | pickup | coupe | convertible | wagon | minivan | van")
        value = normalized_body_type
    return NormalizedWishlistFilter(field=field, operator=operator, value=value)


def trigger_initial_run_for_wishlist(db: Session, wishlist: Wishlist, *, run_reason: str = "wishlist_created") -> Dict[str, Any]:
    """Agenda a primeira execução de uma wishlist recém-criada no pipeline oficial."""
    if not wishlist:
        return {"triggered": 0, "ok": 0, "skipped": 0, "failed": 0, "sources": []}

    allowed_map = allowed_sources_for_wishlists(db, [wishlist])
    sources = sorted(allowed_map.get(wishlist.id) or [])
    if not sources:
        log(
            db,
            "info",
            "wishlist",
            "initial_run_skipped_no_sources",
            {
                "wishlist_id": str(wishlist.id),
                "run_reason": run_reason,
            },
            event_type="wishlist_initial_run",
            tags=["wishlist", run_reason, "skipped"],
        )
        db.commit()
        return {"triggered": 0, "ok": 0, "skipped": 1, "failed": 0, "sources": []}

    out = {"triggered": 0, "ok": 0, "skipped": 0, "failed": 0, "sources": []}
    for src in sources:
        plugin = get_source(src)
        if plugin is None:
            out["sources"].append({"source": src, "status": "source_not_registered"})
            out["skipped"] += 1
            continue

        op = classify_source_operational_role(plugin)
        if op.role in {"disabled", "auxiliary", "not_implemented"}:
            out["sources"].append({"source": src, "status": "source_not_eligible"})
            out["skipped"] += 1
            continue

        queue = resolve_source_queue(plugin)
        try:
            inserted = enqueue_job(db, source=src, queue=queue, priority=1, max_attempts=3)
            status = "queued" if inserted else "already_queued"
            logger.info(
                "initial wishlist enqueue source=%s queue=%s wishlist_id=%s status=%s",
                src,
                queue,
                wishlist.id,
                status,
            )
        except SQLAlchemyError as exc:
            db.rollback()
            status = "enqueue_failed"
            logger.warning("initial wishlist enqueue failed source=%s wishlist_id=%s err=%s", src, wishlist.id, exc)
        except Exception as exc:
            db.rollback()
            status = "enqueue_failed"
            logger.warning("initial wishlist enqueue failed source=%s wishlist_id=%s err=%s", src, wishlist.id, exc)
        out["sources"].append({"source": src, "queue": queue, "status": status})
        if status == "queued":
            out["triggered"] += 1
            out["ok"] += 1
        elif status == "already_queued":
            out["skipped"] += 1
        else:
            out["failed"] += 1

    try:
        log(
            db,
            "info",
            "wishlist",
            "initial_run_dispatched",
            {
                "wishlist_id": str(wishlist.id),
                "run_reason": run_reason,
                "triggered": out["triggered"],
                "ok": out["ok"],
                "skipped": out["skipped"],
                "failed": out["failed"],
                "sources": out["sources"],
            },
            event_type="wishlist_initial_run",
            tags=["wishlist", run_reason],
        )
        db.commit()
    except Exception:
        db.rollback()
    return out


def remove_wishlist(db: Session, user_id, index: int):
    wishlists = list_wishlists(db, user_id)
    if index < 1 or index > len(wishlists):
        return False, "Número inválido. Use /wishlist listar."

    w = wishlists[index - 1]
    try:
        _delete_wishlist_explicit(
            db,
            w,
            actor_user_id=user_id,
            caller="wishlists_service.remove_wishlist",
            reason="user_requested_single_delete",
            flow_context="wishlist_remove",
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        return False, "Erro ao remover wishlist: dependências remanescentes inesperadas."
    except SQLAlchemyError:
        db.rollback()
        return False, "Erro ao remover wishlist por falha no banco de dados."
    invalidate_wishlist_summaries_cache(user_id)
    return True, "Wishlist removida."




def remove_all_wishlists(db: Session, user_id):
    """Remove todas as wishlists do usuário com limpeza explícita de dependências."""
    wishlists = list_wishlists(db, user_id)
    try:
        for w in wishlists:
            _delete_wishlist_explicit(
                db,
                w,
                actor_user_id=user_id,
                caller="wishlists_service.remove_all_wishlists",
                reason="user_requested_bulk_delete",
                flow_context="wishlist_clear",
            )
        db.commit()
    except IntegrityError:
        db.rollback()
        return False, "Erro ao remover wishlists: dependências remanescentes inesperadas."
    except SQLAlchemyError:
        db.rollback()
        return False, "Erro ao remover wishlists por falha no banco de dados."
    invalidate_wishlist_summaries_cache(user_id)
    return True, f"{len(wishlists)} wishlists removidas."

def add_filter(db: Session, wishlist_id, field: str, operator: str, value: str):
    try:
        normalized = normalize_wishlist_filter_input(field, operator, value)
    except ValueError as exc:
        return False, str(exc)

    existing = (
        db.query(WishlistFilter)
        .filter(WishlistFilter.wishlist_id == wishlist_id)
        .filter(WishlistFilter.field == normalized.field)
        .filter(WishlistFilter.operator == normalized.operator)
        .filter(WishlistFilter.value == normalized.value)
        .first()
    )
    if existing:
        if existing.is_active:
            return False, "Filtro já existe (duplicado) ou erro ao salvar."
        existing.is_active = True
        db.add(existing)
    else:
        row = WishlistFilter(
            wishlist_id=wishlist_id,
            field=normalized.field,
            operator=normalized.operator,
            value=normalized.value,
        )
        db.add(row)
    try:
        db.commit()
        wishlist = db.query(Wishlist).filter(Wishlist.id == wishlist_id).first()
        if wishlist:
            invalidate_wishlist_summaries_cache(wishlist.user_id)
        return True, "Filtro adicionado."
    except Exception:
        db.rollback()
        return False, "Filtro já existe (duplicado) ou erro ao salvar."


def create_wishlist_with_filters(
    db: Session, user_id, query: str, filters: list[dict | tuple], include_auctions: bool = False
) -> tuple[bool, str, Optional[uuid.UUID]]:
    normalized_filters: list[NormalizedWishlistFilter] = []
    seen: set[tuple[str, str, str]] = set()
    for item in filters or []:
        if isinstance(item, dict):
            raw_field, raw_op, raw_value = item.get("field"), item.get("operator"), item.get("value")
        else:
            raw_field, raw_op, raw_value = item
        try:
            n = normalize_wishlist_filter_input(str(raw_field), str(raw_op), str(raw_value))
        except ValueError as exc:
            return False, str(exc), None
        key = (n.field, n.operator, n.value)
        if key in seen:
            continue
        seen.add(key)
        normalized_filters.append(n)

    ok, msg = add_wishlist(db, user_id, query, enqueue_initial_run=False, include_auctions=include_auctions)
    if not ok:
        return False, msg, None

    # TODO: idealmente add_wishlist retornaria wishlist_id para remover dependência da ordenação por created_at.
    wishlist = (
        db.query(Wishlist)
        .filter(Wishlist.user_id == user_id)
        .order_by(Wishlist.created_at.desc())
        .first()
    )
    if not wishlist:
        return False, "Erro ao localizar wishlist criada.", None

    for n in normalized_filters:
        f_ok, f_msg = add_filter(db, wishlist.id, n.field, n.operator, n.value)
        if not f_ok and "duplicado" not in f_msg.lower():
            return False, f_msg, None

    trigger_initial_run_for_wishlist(db, wishlist, run_reason="wishlist_created")
    return True, "Wishlist e filtros criados com sucesso.", wishlist.id


def add_wishlist_with_initial_summary(
    db: Session,
    user_id,
    query: str,
    include_auctions: bool = False,
) -> WishlistCreateResult:
    ok, msg = add_wishlist(
        db,
        user_id,
        query,
        enqueue_initial_run=False,
        include_auctions=include_auctions,
    )
    if not ok:
        return WishlistCreateResult(ok=False, message=msg)

    wishlist = (
        db.query(Wishlist)
        .filter(Wishlist.user_id == user_id)
        .order_by(Wishlist.created_at.desc())
        .first()
    )
    if not wishlist:
        return WishlistCreateResult(ok=False, message="Erro ao localizar wishlist criada.")

    summary = trigger_initial_run_for_wishlist(db, wishlist, run_reason="wishlist_created")
    return WishlistCreateResult(
        ok=True,
        message="Wishlist criada com sucesso.",
        wishlist_id=wishlist.id,
        initial_run_summary=summary,
    )


def create_wishlist_with_filters_and_initial_summary(
    db: Session,
    user_id,
    query: str,
    filters: list[dict | tuple],
    include_auctions: bool = False,
) -> WishlistCreateResult:
    normalized_filters: list[NormalizedWishlistFilter] = []
    seen: set[tuple[str, str, str]] = set()
    for item in filters or []:
        if isinstance(item, dict):
            raw_field, raw_op, raw_value = item.get("field"), item.get("operator"), item.get("value")
        else:
            raw_field, raw_op, raw_value = item
        try:
            n = normalize_wishlist_filter_input(str(raw_field), str(raw_op), str(raw_value))
        except ValueError as exc:
            return WishlistCreateResult(ok=False, message=str(exc))
        key = (n.field, n.operator, n.value)
        if key in seen:
            continue
        seen.add(key)
        normalized_filters.append(n)

    ok, msg = add_wishlist(db, user_id, query, enqueue_initial_run=False, include_auctions=include_auctions)
    if not ok:
        return WishlistCreateResult(ok=False, message=msg)

    wishlist = (
        db.query(Wishlist)
        .filter(Wishlist.user_id == user_id)
        .order_by(Wishlist.created_at.desc())
        .first()
    )
    if not wishlist:
        return WishlistCreateResult(ok=False, message="Erro ao localizar wishlist criada.")

    for n in normalized_filters:
        f_ok, f_msg = add_filter(db, wishlist.id, n.field, n.operator, n.value)
        if not f_ok and "duplicado" not in f_msg.lower():
            return WishlistCreateResult(ok=False, message=f_msg)

    summary = trigger_initial_run_for_wishlist(db, wishlist, run_reason="wishlist_created")
    return WishlistCreateResult(
        ok=True,
        message="Wishlist e filtros criados com sucesso.",
        wishlist_id=wishlist.id,
        initial_run_summary=summary,
    )


def list_filters(db: Session, wishlist_id):
    return (
        db.query(WishlistFilter)
        .filter(WishlistFilter.wishlist_id == wishlist_id)
        .filter(WishlistFilter.is_active.is_(True))
        .order_by(WishlistFilter.created_at.asc())
        .all()
    )


def remove_filter(db: Session, wishlist_id, index: int):
    filters = list_filters(db, wishlist_id)
    if index < 1 or index > len(filters):
        return False, "Número inválido. Use /wishlist_filter_list <n>"

    f = filters[index - 1]
    wishlist = db.query(Wishlist).filter(Wishlist.id == wishlist_id).first()
    f.is_active = False
    db.add(f)
    db.commit()
    if wishlist:
        invalidate_wishlist_summaries_cache(wishlist.user_id)
    return True, "Filtro removido."


def _delete_wishlist_explicit(
    db: Session,
    wishlist: Wishlist,
    *,
    actor_user_id,
    caller: str,
    reason: str,
    flow_context: str,
) -> None:
    """Centraliza remoção explícita de wishlist com auditoria obrigatória."""
    payload = {
        "wishlist_id": str(wishlist.id),
        "user_id": str(getattr(wishlist, "user_id", actor_user_id)),
        "actor_user_id": str(actor_user_id),
        "caller": caller,
        "reason": reason,
        "flow_context": flow_context,
    }
    logger.info("wishlist_delete_explicit", extra=payload)
    log(
        db,
        "warn",
        "wishlist",
        "wishlist_delete_explicit",
        payload,
        event_type="wishlist_delete_explicit",
    )

    active_filters = (
        db.query(WishlistFilter)
        .filter(WishlistFilter.wishlist_id == wishlist.id)
        .filter(WishlistFilter.is_active.is_(True))
        .all()
    )
    for row in active_filters:
        row.is_active = False
        db.add(row)

    active_tracked = (
        db.query(WishlistTrackedListing)
        .filter(WishlistTrackedListing.wishlist_id == wishlist.id)
        .filter(WishlistTrackedListing.is_active.is_(True))
        .all()
    )
    for row in active_tracked:
        row.is_active = False
        db.add(row)

    wishlist.is_active = False
    wishlist.deleted_at = _utcnow()
    db.add(wishlist)

    payload["soft_deleted_counts"] = {
        "wishlist_filters": len(active_filters),
        "wishlist_tracked_listings": len(active_tracked),
    }
