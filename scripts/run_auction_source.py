from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.sources.auctions.copart import SOURCE_KEY, fetch_copart_lots, get_last_reason

logging.basicConfig(level=logging.INFO)


def run(source: str, limit: int, dry_run: bool) -> int:
    if source != SOURCE_KEY:
        raise ValueError(f"Unsupported source: {source}. Available: {SOURCE_KEY}")

    lots = fetch_copart_lots(limit=limit)
    summary = {"source": source, "fetched": len(lots), "inserted": 0, "updated": 0, "skipped": 0, "errors": 0, "reason": get_last_reason() if not lots else None}

    if dry_run:
        for lot in lots:
            print(json.dumps(lot.to_payload(), default=str, ensure_ascii=False))
        print(json.dumps(summary, ensure_ascii=False))
        return 0

    from app.db.session import SessionLocal
    from app.services.auction_lot_service import upsert_lot

    db = SessionLocal()
    try:
        for lot in lots:
            _, created = upsert_lot(db, lot.to_payload())
            if created:
                summary["inserted"] += 1
            else:
                summary["updated"] += 1
        db.commit()
    except Exception:
        db.rollback()
        summary["errors"] += 1
        raise
    finally:
        db.close()
        print(json.dumps(summary, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    return run(source=args.source, limit=args.limit, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
