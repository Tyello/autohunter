#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.mercadolivre_strategy_probe import run_probe


def parse_args(argv: list[str] | None = None):
    p = argparse.ArgumentParser(description="Mercado Livre strategy probe (manual/read-only)")
    p.add_argument("--query", required=True)
    p.add_argument("--format", choices=("json", "markdown"), default="json")
    p.add_argument("--include-browser", action="store_true")
    p.add_argument("--capture-dir")
    p.add_argument("--limit-strategies", type=int)
    p.add_argument("--external-id")
    p.add_argument("--timeout-ms", type=int, default=30000)
    p.add_argument("--ignore-security-wall", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = run_probe(
        query=args.query,
        capture_dir=args.capture_dir,
        include_browser=args.include_browser,
        external_id=args.external_id,
        timeout_ms=args.timeout_ms,
        limit_strategies=args.limit_strategies,
        ignore_security_wall=args.ignore_security_wall,
    )
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        rec_key = report.get("recommended_strategy_key") or ""
        if not rec_key and isinstance(report.get("recommended_strategy"), dict):
            rs = report["recommended_strategy"]
            rec_key = f"{rs.get('url_strategy', '')}+{rs.get('fetch_strategy', '')}".strip("+")
        print(f"# MercadoLivre Strategy Probe\n\nsummary_status={report['summary_status']}\nrecommended_strategy={rec_key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
