#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from types import SimpleNamespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.scrapers.sources import get_scraper
from app.services.source_dual_run_report import build_dual_run_report, render_dual_run_report_markdown
from app.sources.registry import get_source
from app.sources.types import ScrapeContext


def parse_args(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Run controlled V1 vs V2 dual-run report for one source.")
    parser.add_argument("source", help="source name (initially only mercadolivre)")
    parser.add_argument("--query", help="search query used to build source URL")
    parser.add_argument("--url", help="full search URL")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--debug", action="store_true", help="include full diagnostics payload in markdown output")
    args = parser.parse_args(argv)

    src = (args.source or "").strip().lower()
    if src != "mercadolivre":
        parser.error("dual-run report inicialmente suporta apenas mercadolivre")
    if bool(args.query) == bool(args.url):
        parser.error("informe exatamente um entre --query ou --url")
    if args.limit <= 0:
        parser.error("--limit deve ser > 0")
    return args


def _build_ctx(source: str, plugin) -> ScrapeContext:
    return ScrapeContext(
        source=source,
        force_browser=False,
        browser_fallback_enabled=True,
        extra=dict(getattr(plugin, "default_extra", {}) or {}),
    )


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 2)

    source = (args.source or "").strip().lower()
    plugin = get_source(source)
    v2_scraper = get_scraper(source)
    if plugin is None or plugin.scrape is None:
        print(f"source sem plugin v1 executável: {source}", file=sys.stderr)
        return 2
    if v2_scraper is None:
        print(f"source sem scraper v2 registrado: {source}", file=sys.stderr)
        return 2

    search_url = args.url or plugin.build_url(args.query)
    ctx = _build_ctx(source, plugin)

    try:
        v1_items: list[dict] = []
        v2_items: list[dict] = []
        v1_error = ""
        v2_error = ""
        v2_result = SimpleNamespace(listings=[], warnings=[], blocked=False)

        try:
            v1_items = (plugin.scrape(search_url, ctx=ctx) or [])[: args.limit]
        except Exception as exc:
            v1_error = f"{type(exc).__name__}: {exc}"

        try:
            v2_result = v2_scraper.scrape(search_url, ctx)
            v2_items = (getattr(v2_result, "listings", None) or [])[: args.limit]
        except Exception as exc:
            v2_error = f"{type(exc).__name__}: {exc}"

        report = build_dual_run_report(
            source,
            search_url,
            v1_items=v1_items,
            v2_items=v2_items,
            query=args.query or "",
            v1_error=v1_error,
            v2_error=v2_error,
            v2_blocked=bool(getattr(v2_result, "blocked", False)),
            v2_warnings=list(getattr(v2_result, "warnings", []) or [])[:5],
            v2_metrics=getattr(v2_result, "metrics", None),
        )
        if args.format == "json":
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            md = render_dual_run_report_markdown(report)
            if args.debug:
                md += "\n\n## diagnostics\n```json\n" + json.dumps(report.get("diagnostics", {}), ensure_ascii=False, indent=2) + "\n```"
            print(md)
        return 0
    except Exception as exc:
        print(f"erro ao executar dual-run report: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
