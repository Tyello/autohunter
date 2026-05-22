from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.source_v2_inventory import build_source_v2_inventory, render_markdown


def _build_inventory_with_optional_db(no_db: bool) -> list[dict]:
    if no_db:
        return build_source_v2_inventory(db=None)

    try:
        from app.db.session import SessionLocal

        with SessionLocal() as db:
            return build_source_v2_inventory(db=db)
    except Exception:
        return build_source_v2_inventory(db=None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build V1/V2 source coverage inventory")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--no-db", action="store_true", help="Skip DB reads and use plugin defaults only")
    args = parser.parse_args(argv)

    inventory = _build_inventory_with_optional_db(no_db=args.no_db)

    if args.format == "json":
        print(json.dumps(inventory, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_markdown(inventory))

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
