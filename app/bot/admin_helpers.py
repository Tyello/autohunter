from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, Optional

AUCTION_SETTINGS_LIMITS = {
    "scheduler_minutes": (15, 1440),
    "max_wishlists_per_run": (1, 200),
    "max_per_wishlist": (1, 3),
    "max_per_user_per_day": (1, 10),
    "min_score": (0, 100),
    "max_lot_age_hours": (0, 720),
}


def sample_to_match_like(sample: Dict[str, Any]) -> SimpleNamespace:
    payload = sample if isinstance(sample, dict) else {}
    mapped = {
        "wishlist_query": payload.get("wishlist_query"),
        "title": payload.get("title"),
        "source": payload.get("source"),
        "source_label": payload.get("source_label"),
        "score": payload.get("score"),
        "current_bid": payload.get("current_bid"),
        "initial_bid": payload.get("initial_bid"),
        "url": payload.get("url"),
        "year": payload.get("year"),
        "mileage_km": payload.get("mileage_km"),
        "auction_end_at": payload.get("auction_end_at") or payload.get("ends_at"),
        "city": payload.get("city"),
        "state": payload.get("state"),
        "location": payload.get("location"),
        "item_type": payload.get("item_type"),
        "total_bids": payload.get("total_bids"),
    }
    if not mapped["city"] and not mapped["state"] and mapped.get("location"):
        location = str(mapped.get("location") or "").strip()
        if "/" in location:
            city, state = location.split("/", 1)
            mapped["city"] = city.strip() or None
            mapped["state"] = state.strip() or None
    return SimpleNamespace(**mapped)


def render_rejection_reason_label(reason: Any) -> str:
    key = str(reason or "").strip().lower()
    labels = {
        "stale_lot": "lote antigo",
        "missing_lot_updated_at": "sem data de atualização",
        "score_below_min": "score abaixo do mínimo",
        "item_type_not_allowed": "tipo bloqueado",
        "missing_item_type": "sem tipo",
        "filters_not_matched": "filtros não compatíveis",
        "text_score_zero": "sem match textual",
        "duplicate": "duplicado",
        "daily_limit": "limite diário",
    }
    return labels.get(key, key or "-")


def fmt_dt(dt: Optional[datetime]) -> str:
    if not dt:
        return "-"
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_admin_bool(raw: str) -> bool | None:
    v = str(raw or "").strip().lower()
    if v in {"true", "1", "sim", "yes", "on"}:
        return True
    if v in {"false", "0", "nao", "não", "no", "off"}:
        return False
    return None


def short(s: Optional[str], n: int = 140) -> str:
    s = (s or "").strip()
    if not s:
        return "-"
    s = " ".join(s.split())
    return s if len(s) <= n else s[: max(0, n - 3)] + "..."
