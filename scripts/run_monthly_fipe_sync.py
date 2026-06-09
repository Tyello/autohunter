#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.db.session import SessionLocal
from app.services.fipe_monthly_pipeline_service import run_monthly_fipe_sync


def _print_summary(result: dict) -> None:
    adapter = result.get("adapter") or {}
    catalog_import = result.get("catalog_import") or {}
    catalog_report = result.get("catalog_report") or {}
    coverage = result.get("resolver_coverage") or {}
    plan = result.get("price_plan") or {}

    print("FIPE monthly sync concluído")
    print(f"- modo: {result.get('mode')}")
    print(f"- referência: {result.get('reference_month')}")
    print(f"- input: {result.get('input_path')}")
    print(f"- source: {result.get('source')}")
    print(
        "- adapter: "
        f"total={adapter.get('total', 0)} normalized={adapter.get('normalized', 0)} "
        f"skipped_invalid={adapter.get('skipped_invalid', 0)} "
        f"skipped_missing_price={adapter.get('skipped_missing_price', 0)} "
        f"skipped_missing_model={adapter.get('skipped_missing_model', 0)}"
    )
    print(
        "- catalog import: "
        f"total={catalog_import.get('total', 0)} valid={catalog_import.get('valid', 0)} "
        f"inserted={catalog_import.get('inserted', 0)} updated={catalog_import.get('updated', 0)} "
        f"skipped_invalid={catalog_import.get('skipped_invalid', 0)} dry_run={catalog_import.get('dry_run')}"
    )
    if result.get("mode") == "dry-run":
        print(
            "  observação: catalog_import é simulação do arquivo novo; "
            "nenhuma linha nova de catálogo foi persistida."
        )
        print(
            "  observação: resolver_coverage e price_plan foram calculados "
            "somente sobre o catálogo já persistido no banco."
        )
    print(
        "- catalog atual: "
        f"entries={catalog_report.get('catalog_entries_count', 0)} "
        f"types={json.dumps(catalog_report.get('vehicle_type_counts', {}), ensure_ascii=False, sort_keys=True)}"
    )
    print(
        "- resolver coverage: "
        f"sample={coverage.get('sample_size', 0)} "
        f"status={json.dumps(coverage.get('status_counts', {}), ensure_ascii=False, sort_keys=True)}"
    )
    print(
        "- fipe_prices plan/apply: "
        f"planned_inserts={plan.get('planned_inserts_count', 0)} "
        f"would_updates={plan.get('would_update_count', 0)} "
        f"inserted={plan.get('inserted_count', 0)} updated={plan.get('updated_count', 0)} "
        f"dry_run={plan.get('dry_run', result.get('mode') == 'dry-run')}"
    )
    print(f"- fipe_prices atuais no mês: {result.get('fipe_prices_count', 0)}")
    warnings = result.get("warnings") or []
    for warning in warnings:
        print(f"⚠️ warning operacional: {warning}")
    print(
        "Próximo passo: revisar os contadores acima e executar com --apply "
        "apenas se o dry-run estiver consistente."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pipeline operacional mensal FIPE local do AutoHunter.")
    parser.add_argument("--reference-month", required=True, help="Competência FIPE no formato YYYY-MM")
    parser.add_argument("--input", required=True, help="Arquivo JSON/CSV exportado pelo pipeline externo")
    parser.add_argument("--format", choices=["external-pipeline"], default="external-pipeline")
    parser.add_argument("--source", default="external_pipeline")
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Amostra máxima de listings para coverage/plan (cap interno 200/500)",
    )
    parser.add_argument("--min-confidence", type=int, default=80)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    try:
        with SessionLocal() as db:
            result = run_monthly_fipe_sync(
                db,
                reference_month=args.reference_month,
                input_path=Path(args.input),
                input_format=args.format,
                source=args.source,
                apply=bool(args.apply),
                limit=args.limit,
                min_confidence=args.min_confidence,
            )
    except Exception as exc:
        print(f"FIPE monthly sync falhou: {exc}")
        return 1

    _print_summary(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
