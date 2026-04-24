#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.settings import settings

TABLE_ORDER = [
    "users",
    "wishlists",
    "wishlist_filters",
    "wishlist_tracked_listings",
    "car_listings",
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


def _insert_on_conflict_do_nothing(conn, table: str, rows: list[dict]) -> int:
    if not rows:
        return 0
    inserted = 0
    for row in rows:
        cols = list(row.keys())
        values = {k: row[k] for k in cols}
        col_sql = ", ".join(cols)
        val_sql = ", ".join([f":{c}" for c in cols])
        sql = text(f"INSERT INTO {table} ({col_sql}) VALUES ({val_sql}) ON CONFLICT (id) DO NOTHING")
        res = conn.execute(sql, values)
        inserted += int(res.rowcount or 0)
    return inserted


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore mínimo de dados core do AutoHunter")
    parser.add_argument("--input", required=True, help="Arquivo JSON de backup")
    parser.add_argument("--apply", action="store_true", help="Aplica restore; sem essa flag roda dry-run")
    args = parser.parse_args()

    database_url = _validate_database_url()

    with open(args.input, "r", encoding="utf-8") as f:
        payload = json.load(f)

    data = payload.get("data") or {}
    if not isinstance(data, dict):
        raise SystemExit("Formato inválido: chave data ausente/inválida")

    dry_run = not bool(args.apply)
    print(f"Modo: {'DRY-RUN' if dry_run else 'APPLY'}")

    engine = create_engine(database_url)
    with engine.begin() as conn:
        for table in TABLE_ORDER:
            rows = data.get(table) or []
            if not rows:
                continue
            if dry_run:
                print(f"[dry-run] {table}: {len(rows)} rows (nenhuma escrita)")
                continue
            inserted = _insert_on_conflict_do_nothing(conn, table, rows)
            print(f"[apply] {table}: input={len(rows)} inserted={inserted} skipped={len(rows)-inserted}")

    print("Restore concluído.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
