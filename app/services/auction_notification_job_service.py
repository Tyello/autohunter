from __future__ import annotations

import logging
from datetime import datetime, timezone
from time import perf_counter

from sqlalchemy.orm import Session

from app.models.app_kv import AppKV
from app.models.wishlist import Wishlist
from app.services.app_kv_service import set_kv
from app.services.auction_notification_service import build_auction_notifications_for_wishlist
from app.services.auction_source_config_service import list_user_eligible_auction_sources

logger = logging.getLogger(__name__)
_DRY_RUN_SAMPLES_KEY = "auction_last_dry_run_samples"
_MAX_SAMPLES = 10


def _truncate(v: str | None, limit: int = 140) -> str | None:
    if not v:
        return v
    s = str(v).strip()
    return s if len(s) <= limit else f"{s[: max(0, limit - 1)]}…"


def _build_sample(wishlist: Wishlist, item: dict) -> dict:
    lot = item.get("lot") if isinstance(item.get("lot"), dict) else {}
    return {
        "wishlist_id": str(wishlist.id),
        "wishlist_query": _truncate(getattr(wishlist, "query", None), 80),
        "user_id": str(getattr(wishlist, "user_id", "")),
        "source": item.get("source") or lot.get("source") or lot.get("source_name") or "-",
        "external_id": item.get("external_id") or lot.get("external_id"),
        "title": _truncate(item.get("title") or lot.get("title"), 120),
        "current_bid": item.get("current_bid") if item.get("current_bid") is not None else lot.get("current_bid"),
        "initial_bid": item.get("initial_bid") if item.get("initial_bid") is not None else lot.get("initial_bid"),
        "score": item.get("score") if item.get("score") is not None else lot.get("score"),
        "url": item.get("url") or lot.get("url"),
        "dedupe_key": item.get("dedupe_key"),
    }


async def run_auction_notification_job(
    db: Session,
    bot=None,
    dry_run: bool = True,
    max_wishlists: int = 20,
    max_per_wishlist: int = 1,
    max_per_user_per_day: int = 3,
    source: str | None = None,
) -> dict:
    started = perf_counter()
    eligible_sources = list_user_eligible_auction_sources(db)
    out = {
        "dry_run": bool(dry_run),
        "wishlists_scanned": 0,
        "wishlists_with_matches": 0,
        "sent": 0,
        "previews": 0,
        "skipped_no_match": 0,
        "skipped_duplicate": 0,
        "skipped_missing_chat_id": 0,
        "skipped_score_below_min": 0,
        "skipped_stale_lot": 0,
        "skipped_missing_lot_updated_at": 0,
        "skipped_daily_limit": 0,
        "errors": 0,
        "messages": [],
    }
    dry_run_samples: list[dict] = []
    if not dry_run and bot is None:
        raise ValueError("bot é obrigatório para envio real")
    if source and source not in eligible_sources:
        raise ValueError("source não elegível para usuário")

    logger.info("auction_notification_job_started", extra={"dry_run": dry_run, "max_wishlists": max_wishlists, "max_per_wishlist": max_per_wishlist, "eligible_sources": sorted(eligible_sources), "source": source})
    try:
        wishlists = (
            db.query(Wishlist)
            .filter(Wishlist.is_active.is_(True), Wishlist.include_auctions.is_(True))
            .order_by(Wishlist.created_at.asc())
            .limit(max(1, int(max_wishlists)))
            .all()
        )
        out["wishlists_scanned"] = len(wishlists)
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for wl in wishlists:
            built = build_auction_notifications_for_wishlist(
                db,
                wl.id,
                source=source,
                limit=max_per_wishlist,
                force=False,
                eligible_sources=eligible_sources,
                allow_no_bid=False,
            )
            out["skipped_duplicate"] += int(built.get("skipped_duplicate", 0) or 0)
            out["skipped_no_match"] += int(built.get("skipped_no_match", 0) or 0)
            out["skipped_missing_chat_id"] += int(built.get("skipped_missing_chat_id", 0) or 0)
            out["skipped_score_below_min"] += int(built.get("skipped_score_below_min", 0) or 0)
            out["skipped_stale_lot"] += int(built.get("skipped_stale_lot", 0) or 0)
            out["skipped_missing_lot_updated_at"] += int(built.get("skipped_missing_lot_updated_at", 0) or 0)
            out["errors"] += int(built.get("errors", 0) or 0)
            if built.get("messages"):
                out["messages"].extend([str(m) for m in built["messages"][:2]])
            items = list(built.get("items", []))
            if not items:
                continue
            out["wishlists_with_matches"] += 1
            if dry_run:
                out["previews"] += len(items)
                for item in items:
                    if len(dry_run_samples) >= _MAX_SAMPLES:
                        break
                    dry_run_samples.append(_build_sample(wl, item))
                continue
            key = f"auction_daily_sent:{wl.user_id}:{day}"
            row = db.query(AppKV).filter(AppKV.key == key).first()
            used = int((row.value or {}).get("count", 0)) if row and isinstance(row.value, dict) else 0
            if used >= int(max_per_user_per_day):
                out["skipped_daily_limit"] += 1
                continue
            remaining = max(0, int(max_per_user_per_day) - used)
            for item in items[:remaining]:
                await bot.send_message(chat_id=item["chat_id"], text=item["text"], disable_web_page_preview=True)
                db.add(AppKV(key=item["dedupe_key"], value={"sent_at": datetime.now(timezone.utc).isoformat(), "type": "auction"}))
                out["sent"] += 1
            new_count = used + min(len(items), remaining)
            if row:
                row.value = {"count": new_count}
                db.add(row)
            else:
                db.add(AppKV(key=key, value={"count": new_count}))
            db.commit()
    except Exception as exc:
        db.rollback()
        out["errors"] += 1
        out["messages"].append(str(exc))
        logger.exception("auction_notification_job_failed")
    duration_ms = int((perf_counter() - started) * 1000)
    summary = {
        "wishlists_scanned": out.get("wishlists_scanned", 0),
        "wishlists_with_matches": out.get("wishlists_with_matches", 0),
        "previews": out.get("previews", 0),
        "skipped_duplicate": out.get("skipped_duplicate", 0),
        "skipped_no_match": out.get("skipped_no_match", 0),
        "skipped_score_below_min": out.get("skipped_score_below_min", 0),
        "skipped_stale_lot": out.get("skipped_stale_lot", 0),
        "skipped_missing_lot_updated_at": out.get("skipped_missing_lot_updated_at", 0),
        "skipped_daily_limit": out.get("skipped_daily_limit", 0),
        "errors": out.get("errors", 0),
    }
    if dry_run:
        set_kv(
            db,
            _DRY_RUN_SAMPLES_KEY,
            {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "samples": dry_run_samples[:_MAX_SAMPLES],
                "summary": summary,
            },
        )
    logger.info("auction_notification_job_finished", extra={**out, "max_wishlists": max_wishlists, "max_per_wishlist": max_per_wishlist, "eligible_sources": sorted(eligible_sources), "duration_ms": duration_ms})
    return out
