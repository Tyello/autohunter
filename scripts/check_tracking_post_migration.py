#!/usr/bin/env python3
"""Validação operacional curta do tracking/wishlist pós-migration.

Uso:
  python scripts/check_tracking_post_migration.py
"""

from __future__ import annotations

from pathlib import Path
import sys

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.session import SessionLocal


CHECKS = {
    "table_exists": """
        select count(*)
        from information_schema.tables
        where table_schema='public' and table_name='wishlist_tracked_listings'
    """,
    "slot_out_of_range": """
        select count(*)
        from wishlist_tracked_listings
        where slot < 1 or slot > 3
    """,
    "wishlists_with_more_than_3": """
        select count(*)
        from (
          select wishlist_id
          from wishlist_tracked_listings
          group by wishlist_id
          having count(*) > 3
        ) x
    """,
    "orphan_wishlist_fk": """
        select count(*)
        from wishlist_tracked_listings wtl
        left join wishlists w on w.id = wtl.wishlist_id
        where w.id is null
    """,
    "orphan_listing_fk_nonnull": """
        select count(*)
        from wishlist_tracked_listings wtl
        left join car_listings cl on cl.id = wtl.car_listing_id
        where wtl.car_listing_id is not null and cl.id is null
    """,
    "wishlists_without_new_filters": """
        select count(*)
        from wishlists w
        where not exists (
            select 1
            from wishlist_filters wf
            where wf.wishlist_id = w.id
              and wf.field in ('color', 'city', 'state')
        )
    """,
}


def main() -> int:
    has_error = False

    with SessionLocal() as db:
        for name, sql in CHECKS.items():
            value = db.execute(text(sql)).scalar() or 0
            print(f"{name}: {value}")

            if name == "table_exists" and int(value) == 0:
                has_error = True
            if name in {"slot_out_of_range", "wishlists_with_more_than_3", "orphan_wishlist_fk", "orphan_listing_fk_nonnull"} and int(value) > 0:
                has_error = True

    if has_error:
        print("RESULT=FAIL")
        return 1

    print("RESULT=OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
