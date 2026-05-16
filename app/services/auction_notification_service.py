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
from app.services.auction_matching_service import _BAD_STATUSES, match_auction_lots_for_wishlist, sort_auction_matches_for_alerting

MAX_NOTIFY_LIMIT = 3


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
        "skipped_missing_chat_id": 0, "errors": 0, "messages": [], "items": []
    }

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
    for m in matches:
        if out["sent"] >= want:
            break
        if not getattr(m, "url", None):
            continue
        has_bid = getattr(m, "current_bid", None) is not None or getattr(m, "initial_bid", None) is not None
        if not allow_no_bid and not has_bid:
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
        dkey = _dedupe_key(str(wishlist.id), m.source, str(lot.external_id))
        if db.query(AppKV).filter(AppKV.key == dkey).first():
            out["skipped_duplicate"] += 1
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
        if not allow_no_bid:
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
