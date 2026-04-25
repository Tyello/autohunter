#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections.abc import Iterable

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from app.core.settings import settings

TABLE_ORDER = [
    "users",
    "wishlists",
    "wishlist_filters",
    "wishlist_tracked_listings",
    "car_listings",
]


def _extract_ids(rows: Iterable[dict], key: str = "id") -> set:
    return {row.get(key) for row in rows if isinstance(row, dict) and row.get(key) is not None}


def _compute_fk_missing(rows: list[dict], fk_name: str, valid_refs: set) -> int:
    if not rows:
        return 0
    missing = 0
    for row in rows:
        ref = row.get(fk_name)
        if ref is not None and ref not in valid_refs:
            missing += 1
    return missing


def _table_exists(conn, table: str) -> bool:
    inspector = inspect(conn)
    return table in inspector.get_table_names()


def _validate_payload_shape(payload: dict) -> tuple[dict, list[str]]:
    issues: list[str] = []
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        raise SystemExit("Formato inválido: chave data ausente/inválida")
    meta = payload.get("meta") or {}
    if not isinstance(meta, dict):
        issues.append("meta ausente/inválida")
    if not meta.get("created_at_utc"):
        issues.append("meta.created_at_utc ausente")
    return data, issues


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


class RestoreReport:
    def __init__(self) -> None:
        self.processed: dict[str, int] = {}
        self.inserted: dict[str, int] = {}
        self.skipped_conflict: dict[str, int] = {}
        self.fk_missing: dict[str, int] = {}
        self.errors: dict[str, int] = {}

    def status(self) -> str:
        if any(v > 0 for v in self.errors.values()):
            return "failed"
        has_skips = any(v > 0 for v in self.skipped_conflict.values()) or any(
            v > 0 for v in self.fk_missing.values()
        )
        return "success_with_skips" if has_skips else "success"


def _print_final_report(report: RestoreReport, *, dry_run: bool) -> None:
    mode = "dry_run" if dry_run else "apply"
    print(f"=== Resumo final ({mode}) ===")
    for table in TABLE_ORDER:
        if table not in report.processed:
            continue
        print(
            f"- {table}: processados={report.processed.get(table, 0)} "
            f"inseridos={report.inserted.get(table, 0)} "
            f"ignorados_conflito={report.skipped_conflict.get(table, 0)} "
            f"fk_ausentes={report.fk_missing.get(table, 0)} "
            f"erros={report.errors.get(table, 0)}"
        )
    print(f"Status final: {report.status()}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore mínimo de dados core do AutoHunter")
    parser.add_argument("--input", required=True, help="Arquivo JSON de backup")
    parser.add_argument("--apply", action="store_true", help="Aplica restore; sem essa flag roda dry-run")
    args = parser.parse_args()

    database_url = _validate_database_url()

    with open(args.input, "r", encoding="utf-8") as f:
        payload = json.load(f)

    data, payload_issues = _validate_payload_shape(payload)

    dry_run = not bool(args.apply)
    print(f"Modo: {'DRY-RUN' if dry_run else 'APPLY'}")
    if dry_run:
        print("Nenhuma escrita será aplicada no banco.")

    report = RestoreReport()

    engine = create_engine(database_url)
    with engine.begin() as conn:
        existing_ids: dict[str, set] = {}
        for table in TABLE_ORDER:
            if table in data and _table_exists(conn, table):
                rows = conn.execute(text(f"SELECT id FROM {table}")).mappings().all()
                existing_ids[table] = _extract_ids(rows)
            else:
                existing_ids[table] = set()

        backup_ids = {table: _extract_ids(data.get(table) or []) for table in TABLE_ORDER}
        fk_base_wishlists = existing_ids.get("wishlists", set()) | backup_ids.get("wishlists", set())
        fk_base_users = existing_ids.get("users", set()) | backup_ids.get("users", set())
        fk_base_car_listings = existing_ids.get("car_listings", set()) | backup_ids.get("car_listings", set())

        risks: list[str] = list(payload_issues)
        for table in TABLE_ORDER:
            rows = data.get(table) or []
            if not rows:
                continue

            current_existing = existing_ids.get(table, set())
            row_ids = _extract_ids(rows)
            already_exists = len([rid for rid in row_ids if rid in current_existing])

            fk_missing = 0
            if table == "wishlists":
                fk_missing = _compute_fk_missing(rows, "user_id", fk_base_users)
            elif table in {"wishlist_filters", "wishlist_tracked_listings"}:
                fk_missing = _compute_fk_missing(rows, "wishlist_id", fk_base_wishlists)
                if table == "wishlist_tracked_listings":
                    for row in rows:
                        car_listing_id = row.get("car_listing_id")
                        if car_listing_id is not None and car_listing_id not in fk_base_car_listings:
                            fk_missing += 1

            insertable = max(0, len(rows) - already_exists - fk_missing)
            if fk_missing > 0:
                risks.append(f"{table}: {fk_missing} linhas com FK ausente")

            report.processed[table] = len(rows)
            report.fk_missing[table] = fk_missing

            if dry_run:
                report.inserted[table] = 0
                report.skipped_conflict[table] = already_exists
                report.errors[table] = 0
                print(
                    f"[dry-run] {table}: processar={len(rows)} existentes={already_exists} "
                    f"fk_ausente={fk_missing} inseriveis={insertable}"
                )
                continue

            inserted = _insert_on_conflict_do_nothing(conn, table, rows)
            skipped = max(0, len(rows) - inserted)
            report.inserted[table] = inserted
            report.skipped_conflict[table] = skipped
            report.errors[table] = 0
            print(f"[apply] {table}: input={len(rows)} inserted={inserted} skipped={skipped}")

        if risks:
            print("Riscos detectados:")
            for risk in risks:
                print(f" - {risk}")
            print("Atenção: há risco de restore parcial.")
        else:
            print("Compatibilidade aparente com schema atual: sem riscos estruturais detectados.")

    _print_final_report(report, dry_run=dry_run)

    print("Restore concluído.")
    return 0 if report.status() != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
