from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.auction_ingestion_service import SUPPORTED_SOURCES, run_auction_ingestion
from app.sources.auctions.copart import fetch_copart_lots, get_last_reason as copart_reason
from app.sources.auctions.vip import fetch_vip_lots, get_last_reason as vip_reason
from app.sources.auctions.mega import fetch_mega_lots, get_last_reason as mega_reason

logging.basicConfig(level=logging.INFO)

def _fetch_source(source: str, limit: int, enrich_details: bool = False):
    if source == "copart_auctions":
        return fetch_copart_lots(limit=limit), copart_reason()
    if source == "vip_auctions":
        return fetch_vip_lots(limit=limit, enrich=enrich_details), vip_reason()
    if source == "mega_auctions":
        return fetch_mega_lots(limit=limit), mega_reason()
    raise ValueError(f"Unsupported source: {source}. Available: {', '.join(sorted(SUPPORTED_SOURCES))}")


def run(source: str, limit: int, dry_run: bool, enrich_details: bool = False) -> int:
    if dry_run:
        lots, reason = _fetch_source(source=source, limit=limit, enrich_details=enrich_details)
        summary = {"source": source, "fetched": len(lots), "inserted": 0, "updated": 0, "skipped": 0, "errors": 0, "reason": reason if not lots else None}
        for lot in lots:
            print(json.dumps(lot.to_payload(), default=str, ensure_ascii=False))
        print(json.dumps(summary, ensure_ascii=False))
        return 0

    summary = run_auction_ingestion(source=source, limit=limit, enrich_details=enrich_details)
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
