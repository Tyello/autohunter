#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.settings import settings

CORE_TABLES = [
    "users",
    "wishlists",
    "wishlist_filters",
    "wishlist_tracked_listings",
]


def _validate_database_url() -> str:
    database_url = (getattr(settings, "database_url", "") or "").strip()
    if not database_url:
        raise SystemExit("DATABASE_URL ausente.")
    try:
        url = make_url(database_url)
    except Exception as exc:
        raise SystemExit(f"DATABASE_URL inválida: {exc}")
    if not str(url.drivername).startswith("postgresql"):
        raise SystemExit("Este script suporta apenas PostgreSQL/Supabase.")
    return database_url


def main() -> int:
    parser = argparse.ArgumentParser(description="Backup mínimo de dados core do AutoHunter")
    parser.add_argument("--output", default="", help="Arquivo de saída JSON")
    parser.add_argument("--include-car-listings", action="store_true", help="Inclui tabela car_listings")
    parser.add_argument("--car-listings-limit", type=int, default=5000, help="Limite de car_listings no backup")
    args = parser.parse_args()

    database_url = _validate_database_url()
    out = args.output.strip() or f"backup_core_data_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"

    tables = list(CORE_TABLES)
    if args.include_car_listings:
        tables.append("car_listings")

    engine = create_engine(database_url)
    payload: dict = {
        "meta": {
            "created_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "backup_version": "1",
            "tables": tables,
            "table_row_counts": {},
        },
        "data": {},
    }

    with engine.connect() as conn:
        for tbl in tables:
            if tbl == "car_listings":
                q = text("SELECT * FROM car_listings ORDER BY created_at DESC LIMIT :lim")
                rows = conn.execute(q, {"lim": max(1, int(args.car_listings_limit or 1))}).mappings().all()
            else:
                rows = conn.execute(text(f"SELECT * FROM {tbl}")).mappings().all()
            payload["data"][tbl] = [dict(r) for r in rows]
            payload["meta"]["table_row_counts"][tbl] = len(rows)
            print(f"[ok] {tbl}: {len(rows)} rows")

    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, default=str)

    print(f"Backup concluído: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
