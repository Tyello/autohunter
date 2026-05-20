from __future__ import annotations

from typing import Any

import httpx

from app.sources.auctions.base import NormalizedAuctionLot

from app.db.session import SessionLocal
from app.models.source_config import SourceConfig
from app.services.source_runs_service import record_run
from app.services.auction_lot_service import upsert_lot
from app.sources.auctions.quality import validate_normalized_auction_lot_candidate
from app.sources.auctions.registry import (
    get_auction_source_definition,
    list_supported_auction_source_keys,
    render_supported_auction_sources_hint,
)

SUPPORTED_SOURCES = list_supported_auction_source_keys()

from app.sources.auctions import mega, sodre, win
from app.sources.auctions.diagnostics import build_auction_source_fetch_diagnostics


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
        cfg = None
        if hasattr(db, "query"):
            cfg = db.query(SourceConfig).filter(SourceConfig.source == source).first()
        score = None
        if cfg and isinstance(getattr(cfg, "extra", None), dict):
            maybe_score = cfg.extra.get("quality_score")
            if maybe_score is not None:
                try:
                    score = int(maybe_score)
                except Exception:
                    score = None
        if cfg and cfg.status:
            status = str(cfg.status).strip()
            if status:
                summary["source_status"] = status
        run_payload = {
            "domain": "auction_ingestion",
            "auction_summary": {
                "found": int(summary.get("fetched", 0) or 0),
                "inserted": int(summary.get("inserted", 0) or 0),
                "updated": int(summary.get("updated", 0) or 0),
                "ignored": int(summary.get("skipped", 0) or 0),
                "errors": int(summary.get("errors", 0) or 0),
                "car_lots": int(sum(1 for lot in lots if str(getattr(lot, "item_type", "") or "").lower() == "car")),
                "with_current_bid_count": int(sum(1 for lot in lots if getattr(lot, "current_bid", None) is not None)),
                "with_initial_bid_count": int(sum(1 for lot in lots if getattr(lot, "initial_bid", None) is not None)),
                "with_auction_start_at_count": int(sum(1 for lot in lots if getattr(lot, "auction_start_at", None) is not None)),
                "with_auction_end_at_count": int(sum(1 for lot in lots if getattr(lot, "auction_end_at", None) is not None)),
                "open_or_live_count": int(sum(1 for lot in lots if str(getattr(lot, "status", "") or "").strip().lower() in {"open", "live"})),
                "score": score,
            },
            "limit": int(limit or 0),
            "enrich_applied": bool(enrich_applied),
        }
        if hasattr(db, "add") and hasattr(db, "flush"):
            record_run(
                db,
                source=source,
                kind="manual",
                status="success" if int(summary.get("errors", 0) or 0) == 0 else "error",
                items_found=int(summary.get("fetched", 0) or 0),
                items_ingested=int(summary.get("inserted", 0) or 0) + int(summary.get("updated", 0) or 0),
                error=None,
                payload=run_payload,
            )
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


def inspect_auction_source(source: str, limit: int = 5, enrich_details: bool = False, detail_url: str | None = None) -> dict[str, Any]:
    definition = get_auction_source_definition(source)
    if definition is None:
        raise ValueError(f"Unsupported source: {source}. {render_supported_auction_sources_hint()}")

    source = definition.key
    enrich_applied = bool(enrich_details and definition.supports_enrich)
    lots: list[NormalizedAuctionLot] = []
    reason = None
    diagnostics = None
    if detail_url:
        with httpx.Client(timeout=15.0, follow_redirects=True, headers={"User-Agent": "AutoHunter/1.0 (+experimental)"}) as client:
            resp = client.get(detail_url)
            html = getattr(resp, "text", "")
            diagnostics = build_auction_source_fetch_diagnostics(resp, html, detail_url)
            if resp.status_code >= 400:
                reason = f"http_{resp.status_code}_detail_fetch_failed"
            elif source == "win_auctions":
                ext = win.parse_win_external_id_from_url(detail_url)
                if not ext:
                    reason = "invalid_detail_url"
                else:
                    base = NormalizedAuctionLot(source=source, external_id=ext, url=detail_url)
                    lot = win._enrich_win_detail(client, base)  # type: ignore[attr-defined]
                    if lot.status in (None, "", "unknown") or lot.current_bid is None or lot.auction_end_at is None:
                        diagnostics = diagnostics or {}
                        detail_diagnostics = diagnostics.get("detail_diagnostics") or {}
                        detail_diagnostics["win_detail"] = win.build_win_detail_diagnostics(html)
                        diagnostics["detail_diagnostics"] = detail_diagnostics
                    lots = [lot] if (lot.title or lot.current_bid is not None or lot.initial_bid is not None) else []
                    reason = None if lots else "detail_without_extractable_signals"
            elif source == "mega_auctions":
                lot = mega.parse_mega_detail_html(html, detail_url)
                lots = [lot] if (lot.title or lot.current_bid is not None or lot.initial_bid is not None) else []
                reason = None if lots else "detail_without_extractable_signals"
            elif source == "sodre_auctions":
                lot = sodre.parse_sodre_detail_html(html, detail_url)
                lots = [lot] if (lot.title or lot.current_bid is not None or lot.initial_bid is not None) else []
                reason = None if lots else "detail_without_extractable_signals"
            else:
                reason = "detail_inspect_not_supported_for_source"
    else:
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
        "diagnostics": diagnostics or _get_source_diagnostics(source),
        "detail_url": detail_url,
        "candidates": candidates,
    }
