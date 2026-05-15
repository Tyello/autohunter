from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.auction_ingestion_service import run_auction_ingestion
from app.sources.auctions.registry import (
    get_auction_source_definition,
    render_supported_auction_sources_hint,
    resolve_auction_source_alias,
)

logging.basicConfig(level=logging.INFO)


def _fetch_source(source: str, limit: int, enrich_details: bool = False):
    definition = get_auction_source_definition(source)
    if definition is None:
        raise ValueError(f"Unsupported source: {source}. {render_supported_auction_sources_hint()}")

    enrich_applied = bool(enrich_details and definition.supports_enrich)
    if definition.supports_enrich:
        lots = definition.fetcher(limit=limit, enrich=enrich_applied)
    else:
        lots = definition.fetcher(limit=limit)
    return definition.key, lots, definition.reason_getter(), enrich_applied


def run(source: str, limit: int, dry_run: bool, enrich_details: bool = False) -> int:
    resolved = resolve_auction_source_alias(source)
    if not resolved:
        raise ValueError(f"Unsupported source: {source}. {render_supported_auction_sources_hint()}")

    if dry_run:
        source_key, lots, reason, enrich_applied = _fetch_source(source=resolved, limit=limit, enrich_details=enrich_details)
        summary = {"source": source_key, "fetched": len(lots), "inserted": 0, "updated": 0, "skipped": 0, "errors": 0, "reason": reason if not lots else None, "enrich_applied": enrich_applied}
        for lot in lots:
            print(json.dumps(lot.to_payload(), default=str, ensure_ascii=False))
        print(json.dumps(summary, ensure_ascii=False))
        return 0

    summary = run_auction_ingestion(source=resolved, limit=limit, enrich_details=enrich_details)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--enrich-details", action="store_true")
    args = parser.parse_args()
    return run(source=args.source, limit=args.limit, dry_run=args.dry_run, enrich_details=args.enrich_details)


if __name__ == "__main__":
    raise SystemExit(main())
