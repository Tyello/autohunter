#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys

from app.scheduler.fipe_update_job import run_monthly_fipe_update_once


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Roda o job mensal FIPE (crawler + sync) imediatamente, fora do agendamento."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Obrigatório: confirma que você quer rodar o job completo agora (crawler contra a API real da FIPE + escrita no banco).",
    )
    parser.add_argument(
        "--limit-brands",
        type=int,
        default=None,
        help="Limita o crawler às N primeiras marcas retornadas pela API (smoke test rápido).",
    )
    args = parser.parse_args(argv)

    if not args.force:
        print("Nada foi executado. Use --force para rodar o job mensal FIPE agora.")
        return 1

    try:
        run = run_monthly_fipe_update_once(limit_brands=args.limit_brands)
    except Exception as exc:
        print(f"FIPE monthly job falhou: {exc}")
        return 1

    print(f"status={run.status} reference_month={run.reference_month} updated_rows={run.updated_rows} error={run.error_message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
