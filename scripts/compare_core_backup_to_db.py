#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from app.core.settings import settings

REQUIRED_TABLES = [
    "users",
    "wishlists",
    "wishlist_filters",
    "wishlist_tracked_listings",
]
OPTIONAL_TABLES = ["car_listings"]


class CompareReport:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.errors: list[str] = []

    @property
    def has_diff(self) -> bool:
        return any(int(row.get("diff", 0)) != 0 for row in self.rows)

    @property
    def ok(self) -> bool:
        return not self.errors and not self.has_diff


def _validate_database_url() -> str:
    database_url = (getattr(settings, "database_url", "") or "").strip()
    if not database_url:
        raise SystemExit("DATABASE_URL ausente.")
    try:
        url = make_url(database_url)
    except Exception as exc:
        raise SystemExit(f"DATABASE_URL inválida: {exc}")
    if str(url.drivername).startswith("sqlite"):
        raise SystemExit("SQLite não é suportado para comparação backup vs DB.")
    if not str(url.drivername).startswith("postgresql"):
        raise SystemExit("Este script suporta apenas PostgreSQL/Supabase.")
    return database_url


def _load_payload(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise SystemExit("Backup inválido: raiz deve ser objeto JSON.")
    return payload


def _required_tables_from_backup(payload: dict[str, Any]) -> list[str]:
    meta = payload.get("meta") or {}
    table_row_counts = meta.get("table_row_counts")
    if not isinstance(table_row_counts, dict):
        raise SystemExit("Backup inválido: meta.table_row_counts ausente/inválido.")

    missing = [table for table in REQUIRED_TABLES if table not in table_row_counts]
    if missing:
        raise SystemExit(f"Backup inválido: table_row_counts sem tabelas obrigatórias: {', '.join(missing)}")

    tables = list(REQUIRED_TABLES)
    for optional in OPTIONAL_TABLES:
        if optional in table_row_counts:
            tables.append(optional)
    return tables


def compare_backup_to_db(payload: dict[str, Any], db_counts: dict[str, int]) -> CompareReport:
    report = CompareReport()
    table_row_counts = ((payload.get("meta") or {}).get("table_row_counts") or {})
    if not isinstance(table_row_counts, dict):
        report.errors.append("Backup inválido: meta.table_row_counts ausente/inválido.")
        return report

    tables = _required_tables_from_backup(payload)
    for table in tables:
        expected = int(table_row_counts.get(table) or 0)
        found = int(db_counts.get(table) or 0)
        report.rows.append(
            {
                "table": table,
                "expected": expected,
                "found": found,
                "diff": found - expected,
            }
        )

    return report


def _fetch_db_counts(database_url: str, tables: list[str]) -> dict[str, int]:
    engine = create_engine(database_url)
    counts: dict[str, int] = {}
    with engine.connect() as conn:
        inspector = inspect(conn)
        existing = set(inspector.get_table_names())
        missing_in_db = [table for table in tables if table not in existing]
        if missing_in_db:
            raise SystemExit(f"Banco destino sem tabelas esperadas: {', '.join(missing_in_db)}")

        for table in tables:
            counts[table] = int(conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0)
    return counts


def _print_report(report: CompareReport) -> None:
    print("=== Comparação Backup vs DB ===")
    for row in report.rows:
        print(
            f"- {row['table']}: expected={row['expected']} found={row['found']} diff={row['diff']}"
        )

    if report.errors:
        print("\nErros:")
        for error in report.errors:
            print(f" - {error}")

    if report.ok:
        print("\nResultado: OK (contagens compatíveis)")
    elif report.has_diff:
        print("\nResultado: DIVERGENTE (há diferenças relevantes)")
    else:
        print("\nResultado: INVÁLIDO")


def main() -> int:
    parser = argparse.ArgumentParser(description="Compara contagens do backup core com contagens atuais no DB")
    parser.add_argument("--input", required=True, help="Arquivo JSON de backup")
    args = parser.parse_args()

    payload = _load_payload(args.input)
    tables = _required_tables_from_backup(payload)
    database_url = _validate_database_url()
    db_counts = _fetch_db_counts(database_url, tables)

    report = compare_backup_to_db(payload, db_counts)
    _print_report(report)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
