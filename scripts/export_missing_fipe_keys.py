from __future__ import annotations

import argparse
import csv
from pathlib import Path

from app.db.session import SessionLocal
from app.services.fipe_prices_import_service import build_fipe_coverage_report


CSV_COLUMNS = ["vehicle_key", "listings_count", "reference_month", "fipe_price", "currency"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Exporta top chaves FIPE ausentes para preenchimento manual.")
    parser.add_argument("--reference-month", default=None)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--output", required=True)
    parser.add_argument("--force", action="store_true", default=False)
    args = parser.parse_args(argv)

    out_path = Path(args.output)
    if out_path.exists() and not args.force:
        print(f"Erro: arquivo já existe: {out_path}. Use --force para sobrescrever.")
        return 1

    with SessionLocal() as db:
        try:
            report = build_fipe_coverage_report(db, reference_month=args.reference_month, limit=args.limit)
        except Exception as exc:
            print(f"Erro ao gerar coverage: {exc}")
            return 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for item in report.get("top_missing_keys", []):
            writer.writerow(
                {
                    "vehicle_key": item["vehicle_key"],
                    "listings_count": item["count"],
                    "reference_month": report["reference_month"],
                    "fipe_price": "",
                    "currency": "BRL",
                }
            )

    print(f"Export concluído: {out_path}")
    print(f"competência: {report['reference_month']}")
    print(f"linhas: {len(report.get('top_missing_keys', []))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
