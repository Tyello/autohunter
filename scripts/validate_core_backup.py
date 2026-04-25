#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from typing import Any

EXPECTED_TABLES = [
    "users",
    "wishlists",
    "wishlist_filters",
    "wishlist_tracked_listings",
]


class ValidationReport:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.table_counts: dict[str, int] = {}

    @property
    def is_valid(self) -> bool:
        return not self.errors


def _as_list(value: Any, *, field_name: str, report: ValidationReport) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        report.errors.append(f"Tabela '{field_name}' inválida: esperado array.")
        return []
    normalized: list[dict[str, Any]] = []
    for idx, row in enumerate(value):
        if not isinstance(row, dict):
            report.errors.append(f"Tabela '{field_name}' possui item inválido no índice {idx}: esperado objeto.")
            continue
        normalized.append(row)
    return normalized


def validate_payload(payload: dict[str, Any]) -> ValidationReport:
    report = ValidationReport()

    if not isinstance(payload, dict):
        report.errors.append("Backup inválido: raiz deve ser objeto JSON.")
        return report

    meta = payload.get("meta")
    if not isinstance(meta, dict):
        report.errors.append("Backup inválido: campo 'meta' ausente/inválido.")
    else:
        for required_meta in ("created_at_utc", "tables"):
            if required_meta not in meta:
                report.errors.append(f"Meta inválida: campo '{required_meta}' ausente.")

    data = payload.get("data")
    if not isinstance(data, dict):
        report.errors.append("Backup inválido: campo 'data' ausente/inválido.")
        return report

    missing_tables = [tbl for tbl in EXPECTED_TABLES if tbl not in data]
    if missing_tables:
        report.errors.append(f"Tabelas obrigatórias ausentes: {', '.join(missing_tables)}")

    users = _as_list(data.get("users", []), field_name="users", report=report)
    wishlists = _as_list(data.get("wishlists", []), field_name="wishlists", report=report)
    filters = _as_list(data.get("wishlist_filters", []), field_name="wishlist_filters", report=report)
    tracked = _as_list(data.get("wishlist_tracked_listings", []), field_name="wishlist_tracked_listings", report=report)
    car_listings = _as_list(data.get("car_listings", []), field_name="car_listings", report=report)

    for tbl_name, rows in (
        ("users", users),
        ("wishlists", wishlists),
        ("wishlist_filters", filters),
        ("wishlist_tracked_listings", tracked),
        ("car_listings", car_listings),
    ):
        report.table_counts[tbl_name] = len(rows)

    user_ids = {row.get("id") for row in users if row.get("id") is not None}
    wishlist_ids = {row.get("id") for row in wishlists if row.get("id") is not None}
    car_listing_ids = {row.get("id") for row in car_listings if row.get("id") is not None}

    for row in wishlists:
        user_id = row.get("user_id")
        if user_id is not None and user_id not in user_ids:
            report.errors.append(f"wishlist id={row.get('id')} referencia user_id ausente: {user_id}")

    for row in filters:
        wishlist_id = row.get("wishlist_id")
        if wishlist_id is not None and wishlist_id not in wishlist_ids:
            report.errors.append(
                f"wishlist_filter id={row.get('id')} referencia wishlist_id ausente: {wishlist_id}"
            )

    for row in tracked:
        wishlist_id = row.get("wishlist_id")
        if wishlist_id is not None and wishlist_id not in wishlist_ids:
            report.errors.append(
                f"wishlist_tracked_listing id={row.get('id')} referencia wishlist_id ausente: {wishlist_id}"
            )

        # car_listing_id pode ser nulo; só validamos referência quando presente e tabela disponível
        car_listing_id = row.get("car_listing_id")
        if car_listing_id is not None and car_listing_ids and car_listing_id not in car_listing_ids:
            report.errors.append(
                f"wishlist_tracked_listing id={row.get('id')} referencia car_listing_id ausente: {car_listing_id}"
            )

    return report


def _print_report(report: ValidationReport) -> None:
    print("=== Relatório de Validação de Backup Core ===")
    for table, count in sorted(report.table_counts.items()):
        print(f"- {table}: {count} registros")

    if report.warnings:
        print("\nAvisos:")
        for warning in report.warnings:
            print(f"  - {warning}")

    if report.errors:
        print("\nErros:")
        for error in report.errors:
            print(f"  - {error}")
        print("\nResultado: INVÁLIDO")
    else:
        print("\nResultado: VÁLIDO")


def main() -> int:
    parser = argparse.ArgumentParser(description="Valida estrutura e integridade básica de backup core")
    parser.add_argument("--input", required=True, help="Arquivo JSON de backup")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        payload = json.load(f)

    report = validate_payload(payload)
    _print_report(report)
    return 0 if report.is_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
