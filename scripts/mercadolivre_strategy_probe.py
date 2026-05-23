from __future__ import annotations

import argparse
import json

from app.services.mercadolivre_strategy_probe import ProbeOptions, run_probe


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True)
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    parser.add_argument("--include-browser", action="store_true")
    parser.add_argument("--capture-dir")
    parser.add_argument("--limit-strategies", type=int)
    parser.add_argument("--external-id")
    parser.add_argument("--timeout-ms", type=int, default=30000)
    args = parser.parse_args()

    result = run_probe(
        query=args.query,
        options=ProbeOptions(include_browser=args.include_browser, capture_dir=args.capture_dir, timeout_ms=args.timeout_ms),
        external_id=args.external_id,
        limit_strategies=args.limit_strategies,
    )
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"# MercadoLivre Strategy Probe\n\n- query: {result['query']}\n- summary_status: {result['summary_status']}\n- recommended_strategy: {result['recommended_strategy']}\n")
        for att in result["attempts"]:
            print(f"- {att['url_strategy']} / {att['fetch_strategy']}: score={att['useful_data_score']} ok={att['fetch_ok']} blocked={att['fetch_blocked']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
