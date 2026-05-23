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
    parser = argparse.ArgumentParser(description="Manual Mercado Livre fetch strategy probe (read-only).")
    parser.add_argument("--query", required=True)
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--capture-dir", help="Optional dir to save HTML/JSON responses. Never enabled by default.")
    parser.add_argument("--include-browser", action="store_true", help="Include explicit Playwright diagnostic strategies (manual/read-only)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = run_probe(query=args.query, capture_dir=args.capture_dir, include_browser=args.include_browser)
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"# MercadoLivre strategy probe\n\nsummary_status={report['summary_status']}\nrecommended_strategy={report['recommended_strategy']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
