from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from app.db.session import SessionLocal
from app.services.fipe_prices_import_service import upsert_fipe_prices


def _load_rows(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"arquivo não encontrado: {path}")
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("JSON inválido: esperado list[dict]")
        return [row for row in payload if isinstance(row, dict)]
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        cols = set(reader.fieldnames or [])
        if not {"vehicle_key", "fipe_price"}.issubset(cols):
            raise ValueError("CSV inválido: colunas obrigatórias vehicle_key,fipe_price")
        return [dict(r) for r in reader]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Importador operacional de FIPE local (CSV/JSON).")
    parser.add_argument("--file", required=True)
    parser.add_argument("--reference-month", default=None)
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--apply", action="store_true", default=False)
    args = parser.parse_args(argv)

    dry_run = not args.apply if not args.dry_run else True
    print("DATABASE_URL=***")

    try:
        rows = _load_rows(Path(args.file))
    except Exception as exc:
        print(f"Erro ao carregar arquivo: {exc}")
        return 1

    with SessionLocal() as db:
        try:
            result = upsert_fipe_prices(db, rows, reference_month=args.reference_month, dry_run=dry_run)
        except Exception as exc:
            print(f"Erro no import: {exc}")
            return 1

    print("Resumo FIPE import:")
    for key in ["total", "valid", "inserted", "updated", "skipped_invalid", "dry_run"]:
        print(f"- {key}: {result[key]}")

    if result["valid"] == 0:
        print("Erro: zero linhas válidas para importar.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
