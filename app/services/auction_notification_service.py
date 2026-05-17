from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.bot.renderers import render_auction_alert
from app.models.app_kv import AppKV
from app.models.auction_lot import AuctionLot
from app.models.user import User
from app.models.wishlist import Wishlist
from app.services.auction_notification_settings_service import get_auction_notification_runtime_settings
from app.services.auction_source_categories_service import is_auction_item_type_allowed, normalize_item_type
from app.services.auction_matching_service import _BAD_STATUSES, match_auction_lots_for_wishlist, sort_auction_matches_for_alerting

MAX_NOTIFY_LIMIT = 3
MAX_REJECTIONS_PER_WISHLIST = 5


def _to_uuid(value: Any):
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except Exception:
        return None


def _normalize_limit(limit: int | None) -> int:
    try:
        value = int(limit or 1)
    except Exception:
        return 1
    return max(1, min(MAX_NOTIFY_LIMIT, value))


def _dedupe_key(wishlist_id: str, source: str, lot_external_id: str) -> str:
    return f"auction:{wishlist_id}:{source}:{lot_external_id}"


def _is_auction_match_notification_eligible(match, lot, *, min_score: int, max_age_hours: int, now: datetime | None = None) -> tuple[bool, str]:
    score = getattr(match, "score", 0)
    try:
        score_v = int(score if score is not None else 0)
    except Exception:
        score_v = 0
    if score_v < int(min_score):
        return False, "score_below_min"

    if int(max_age_hours) <= 0:
        return True, "ok"

    updated_at = (
        getattr(lot, "updated_at", None)
        or getattr(match, "updated_at", None)
        or getattr(lot, "created_at", None)
    )
    if updated_at is None:
        return False, "missing_lot_updated_at"
    if getattr(updated_at, "tzinfo", None) is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    now_ref = now or datetime.now(timezone.utc)
    if (now_ref - updated_at).total_seconds() > int(max_age_hours) * 3600:
        return False, "stale_lot"
    return True, "ok"


def build_auction_notifications_for_wishlist(
    db: Session,
    wishlist_id,
    source: str | None = None,
    limit: int = 1,
    force: bool = False,
    eligible_sources: set[str] | None = None,
    allow_no_bid: bool = False,
) -> dict:
    out = {
        "wishlist_id": str(wishlist_id), "sent": 0, "skipped_duplicate": 0, "skipped_no_match": 0,
        "skipped_missing_chat_id": 0, "skipped_score_below_min": 0, "skipped_stale_lot": 0, "skipped_missing_lot_updated_at": 0, "skipped_item_type_not_allowed": 0, "skipped_missing_item_type": 0, "errors": 0, "messages": [], "items": [], "rejections": []
    }
    def _add_rejection(match, lot, reason: str, detail: str):
        if len(out["rejections"]) >= MAX_REJECTIONS_PER_WISHLIST:
            return
        lot_obj = lot or match
        current_bid = getattr(lot_obj, "current_bid", None)
        out["rejections"].append({
            "wishlist_id": str(out.get("wishlist_id") or wishlist_id),
            "wishlist_query": getattr(wishlist, "query", None) if "wishlist" in locals() else None,
            "source": getattr(match, "source", None) if match is not None else getattr(lot_obj, "source", None),
            "lot_id": str(getattr(lot, "id", "") or getattr(match, "lot_id", "") or ""),
            "external_id": str(getattr(lot, "external_id", "") or ""),
            "title": getattr(match, "title", None) or getattr(lot, "title", None),
            "item_type": normalize_item_type(getattr(lot_obj, "item_type", None)),
            "year": getattr(lot_obj, "year", None),
            "current_bid": str(current_bid) if current_bid is not None else None,
            "updated_at": getattr(lot_obj, "updated_at", None).isoformat() if getattr(lot_obj, "updated_at", None) else None,
            "score": getattr(match, "score", None) if match is not None else None,
            "reason": reason,
            "detail": detail,
        })

    target_id = _to_uuid(wishlist_id)
    if not target_id:
        out["errors"] += 1
        out["messages"].append("Wishlist não encontrada.")
        return out

    wishlist = db.query(Wishlist).filter(Wishlist.id == target_id).first()
    if not wishlist:
        out["errors"] += 1
        out["messages"].append("Wishlist não encontrada.")
        return out
    out["wishlist_id"] = str(wishlist.id)

    user = db.query(User).filter(User.id == wishlist.user_id).first() if wishlist.user_id else None
    if not user:
        out["errors"] += 1
        out["messages"].append("Wishlist sem usuário associado.")
        return out
    if not getattr(user, "telegram_chat_id", None) or int(getattr(user, "telegram_chat_id", 0) or 0) <= 0:
        out["skipped_missing_chat_id"] += 1
        out["messages"].append("Usuário sem telegram_chat_id.")
        return out

    if not force and not bool(getattr(wishlist, "include_auctions", False)):
        out["errors"] += 1
        out["messages"].append(
            f"Esta busca não está habilitada para leilões. Use /admin auctions wishlist {wishlist.id} enable para habilitar ou rode com --force para diagnóstico."
        )
        return out

    matches = match_auction_lots_for_wishlist(
        db, wishlist, source=source, limit=_normalize_limit(limit) * 4, eligible_sources=eligible_sources
    )
    matches = sort_auction_matches_for_alerting(matches)

    if not matches:
        out["skipped_no_match"] += 1
        out["messages"].append("Sem leilões compatíveis para esta busca.")
        return out

    want = _normalize_limit(limit)
    runtime_cfg = get_auction_notification_runtime_settings(db)
    min_score = int(runtime_cfg["min_score"])
    max_age_hours = int(runtime_cfg["max_lot_age_hours"])
    for m in matches:
        if out["sent"] >= want:
            break
        if not getattr(m, "url", None):
            continue
        has_bid = getattr(m, "current_bid", None) is not None or getattr(m, "initial_bid", None) is not None
        if not allow_no_bid and not has_bid:
            _add_rejection(m, None, "no_bid", "sem lance atual/inicial")
            continue
        status = str(getattr(m, "status", "") or "").strip().lower()
        if not force and status in _BAD_STATUSES:
            continue
        lot_id = _to_uuid(getattr(m, "lot_id", None))
        if not lot_id:
            continue
        lot = db.query(AuctionLot).filter(AuctionLot.id == lot_id).first()
        if not lot or not getattr(lot, "external_id", None):
            continue
        lot_item_type = normalize_item_type(getattr(lot, "item_type", None))
        if lot_item_type is None:
            out["skipped_missing_item_type"] += 1
            _add_rejection(m, lot, "missing_item_type", "item_type ausente")
            continue
        if not is_auction_item_type_allowed(db, m.source, lot_item_type):
            out["skipped_item_type_not_allowed"] += 1
            _add_rejection(m, lot, "item_type_not_allowed", f"tipo {lot_item_type} bloqueado para source")
            continue
        eligible, reason = _is_auction_match_notification_eligible(m, lot, min_score=min_score, max_age_hours=max_age_hours)
        if not eligible:
            if reason == "score_below_min":
                out["skipped_score_below_min"] += 1
                _add_rejection(m, lot, "score_below_min", f"score={getattr(m, 'score', 0)} abaixo de min_score={min_score}")
            elif reason == "stale_lot":
                out["skipped_stale_lot"] += 1
                _add_rejection(m, lot, "stale_lot", f"updated_at fora da janela {max_age_hours}h")
            elif reason == "missing_lot_updated_at":
                out["skipped_missing_lot_updated_at"] += 1
                _add_rejection(m, lot, "missing_lot_updated_at", "updated_at ausente")
            continue
        dkey = _dedupe_key(str(wishlist.id), m.source, str(lot.external_id))
        if db.query(AppKV).filter(AppKV.key == dkey).first():
            out["skipped_duplicate"] += 1
            _add_rejection(m, lot, "dedupe", "alerta já enviado para lote/source/busca")
            continue
        out["items"].append(
            {
                "chat_id": int(user.telegram_chat_id),
                "text": render_auction_alert(m),
                "dedupe_key": dkey,
                "source": getattr(m, "source", None),
                "external_id": str(getattr(lot, "external_id", "") or ""),
                "title": getattr(m, "title", None) or getattr(lot, "title", None),
                "current_bid": getattr(m, "current_bid", None),
                "initial_bid": getattr(m, "initial_bid", None),
                "score": getattr(m, "score", None),
                "url": getattr(m, "url", None),
                "lot_id": str(getattr(lot, "id", "") or ""),
            }
        )
        out["sent"] += 1

    if out["sent"] == 0 and out["skipped_duplicate"] == 0:
        out["skipped_no_match"] += 1
        quality_skips = int(out.get("skipped_score_below_min", 0) or 0) + int(out.get("skipped_stale_lot", 0) or 0) + int(out.get("skipped_missing_lot_updated_at", 0) or 0)
        if quality_skips > 0:
            out["messages"].append("Sem lotes elegíveis para envio após filtros de qualidade: score mínimo ou atualização recente.")
        elif not allow_no_bid:
            out["messages"].append("Sem lotes elegíveis para envio: nenhum match com lance atual ou lance inicial.")
        else:
            out["messages"].append("Sem lotes elegíveis para envio.")
    return out


async def send_auction_notifications_for_wishlist(
    db: Session,
    bot,
    wishlist_id,
    source: str | None = None,
    limit: int = 1,
    force: bool = False,
    eligible_sources: set[str] | None = None,
    allow_no_bid: bool = False,
) -> dict:
    result = build_auction_notifications_for_wishlist(
        db, wishlist_id, source=source, limit=limit, force=force, eligible_sources=eligible_sources, allow_no_bid=allow_no_bid
    )
    sent = 0
    for item in result.get("items", []):
        try:
            await bot.send_message(chat_id=item["chat_id"], text=item["text"], disable_web_page_preview=True)
            db.add(AppKV(key=item["dedupe_key"], value={"sent_at": datetime.now(timezone.utc).isoformat(), "type": "auction"}))
            db.commit()
            sent += 1
        except Exception as exc:
            db.rollback()
            result["errors"] += 1
            result["messages"].append(f"Falha ao enviar alerta: {exc}")
    result["sent"] = sent
    result.pop("items", None)
    return result
