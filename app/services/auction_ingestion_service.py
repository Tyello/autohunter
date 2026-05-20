from __future__ import annotations

from typing import Any

from app.sources.auctions.base import NormalizedAuctionLot

from app.db.session import SessionLocal
from app.services.auction_lot_service import upsert_lot
from app.sources.auctions.quality import validate_normalized_auction_lot_candidate
from app.sources.auctions.registry import (
    get_auction_source_definition,
    list_supported_auction_source_keys,
    render_supported_auction_sources_hint,
)

SUPPORTED_SOURCES = list_supported_auction_source_keys()

from app.sources.auctions import mega, sodre, win


def _get_source_diagnostics(source: str) -> dict[str, Any] | None:
    mapping = {"win_auctions": win.get_last_fetch_diagnostics, "mega_auctions": mega.get_last_fetch_diagnostics, "sodre_auctions": sodre.get_last_fetch_diagnostics}
    getter = mapping.get(source)
    return getter() if getter else None


def run_auction_ingestion(source: str, limit: int, enrich_details: bool = False) -> dict[str, Any]:
    definition = get_auction_source_definition(source)
    if definition is None:
        raise ValueError(f"Unsupported source: {source}. {render_supported_auction_sources_hint()}")

    source = definition.key
    enrich_applied = bool(enrich_details and definition.supports_enrich)
    if definition.supports_enrich:
        lots = definition.fetcher(limit=limit, enrich=enrich_applied)
    else:
        lots = definition.fetcher(limit=limit)
    reason = definition.reason_getter()

    summary: dict[str, Any] = {
        "source": source,
        "fetched": len(lots),
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "errors": 0,
        "reason": reason if not lots else None,
        "skipped_reasons": {},
        "enrich_applied": enrich_applied,
        "ignored_examples": [],
    }

    db = SessionLocal()
    try:
        for lot in lots:
            quality = validate_normalized_auction_lot_candidate(lot)
            if not quality.ok:
                summary["skipped"] += 1
                reason_key = quality.reason or "quality_rejected"
                skipped_reasons: dict[str, int] = summary["skipped_reasons"]
                skipped_reasons[reason_key] = skipped_reasons.get(reason_key, 0) + 1
                if len(summary["ignored_examples"]) < 3:
                    summary["ignored_examples"].append({
                        "reason": reason_key,
                        "source": lot.source,
                        "url": lot.url,
                        "title": lot.title,
                        "fallback_title": ((lot.extras or {}).get("event_title") if isinstance(lot.extras, dict) else None),
                        "text_preview": " ".join(str((lot.raw_payload or {}).get("html_card") or "").split())[:300],
                    })
                continue
            _, created = upsert_lot(db, lot.to_payload())
            if created:
                summary["inserted"] += 1
            else:
                summary["updated"] += 1
        if not summary["skipped_reasons"]:
            summary.pop("skipped_reasons", None)
        db.commit()
        return summary
    except Exception:
        db.rollback()
        summary["errors"] += 1
        raise
    finally:
        db.close()


def inspect_auction_source(source: str, limit: int = 5, enrich_details: bool = False) -> dict[str, Any]:
    definition = get_auction_source_definition(source)
    if definition is None:
        raise ValueError(f"Unsupported source: {source}. {render_supported_auction_sources_hint()}")

    source = definition.key
    enrich_applied = bool(enrich_details and definition.supports_enrich)
    if definition.supports_enrich:
        lots = definition.fetcher(limit=limit, enrich=enrich_applied)
    else:
        lots = definition.fetcher(limit=limit)
    reason = definition.reason_getter()

    def _preview(lot: NormalizedAuctionLot) -> str:
        text = " ".join([
            str(lot.title or ""),
            str(lot.url or ""),
            str(lot.location or ""),
            str((lot.raw_payload or {}).get("html_card") or ""),
        ]).strip()
        return " ".join(text.split())[:300]

    candidates = []
    for idx, lot in enumerate(lots[:limit], start=1):
        quality = validate_normalized_auction_lot_candidate(lot)
        candidates.append({
            "index": idx,
            "url": lot.url,
            "title": lot.title,
            "title_fallback": ((lot.extras or {}).get("event_title") if isinstance(lot.extras, dict) else None),
            "external_id": lot.external_id,
            "item_type": lot.item_type,
            "current_bid": lot.current_bid,
            "initial_bid": lot.initial_bid,
            "year": lot.year,
            "status": lot.status,
            "city": lot.city,
            "state": lot.state,
            "location": lot.location,
            "image": lot.thumbnail_url or ((lot.images or [None])[0]),
            "source": lot.source,
            "detail_url": lot.url,
            "list_url": (lot.extras or {}).get("listing_url") if isinstance(lot.extras, dict) else None,
            "skip_reason": None if quality.ok else (quality.reason or "quality_rejected"),
            "text_preview": _preview(lot),
        })

    return {
        "source": source,
        "limit": limit,
        "enrich_applied": enrich_applied,
        "fetched": len(lots),
        "reason": reason if not lots else None,
        "diagnostics": _get_source_diagnostics(source),
        "candidates": candidates,
    }
