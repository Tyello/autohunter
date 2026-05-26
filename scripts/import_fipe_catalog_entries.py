#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from app.db.session import SessionLocal
from app.services.fipe_monthly_sync_service import start_fipe_sync_run, finish_fipe_sync_run, upsert_fipe_catalog_entries


def _load_rows(path: Path) -> list[dict]:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("JSON deve ser list[dict]")
        return [x for x in data if isinstance(x, dict)]
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Importa catálogo FIPE bruto em staging local")
    parser.add_argument("--file", required=True)
    parser.add_argument("--reference-month", required=True)
    parser.add_argument("--source", default="external_pipeline")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"Arquivo não encontrado: {file_path}")
        return 2

    try:
        rows = _load_rows(file_path)
    except Exception as exc:
        print(f"Falha ao ler arquivo: {exc}")
        return 2

    with SessionLocal() as db:
        run = start_fipe_sync_run(db, reference_month=args.reference_month, source=args.source)
        try:
            result = upsert_fipe_catalog_entries(db, rows, reference_month=args.reference_month, source=args.source, dry_run=not args.apply)
            if result["valid"] == 0:
                finish_fipe_sync_run(db, run.id, status="failed", counters=result, error="zero linhas válidas")
                print("Nenhuma linha válida para importar")
                return 1
            finish_fipe_sync_run(db, run.id, status="completed", counters=result)
        except Exception as exc:
            finish_fipe_sync_run(db, run.id, status="failed", error=str(exc))
            print(str(exc))
            return 1

    print(
        "Resumo: "
        f"total={result['total']} valid={result['valid']} inserted={result['inserted']} "
        f"updated={result['updated']} skipped_invalid={result['skipped_invalid']} dry_run={result['dry_run']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
