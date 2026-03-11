from __future__ import annotations

import argparse
import json

from app.scrapers.webmotors import scrape_webmotors
from app.sources.types import ScrapeContext


def main() -> int:
    parser = argparse.ArgumentParser(description="Debug capture flow for WebMotors.")
    parser.add_argument("--url", required=True, help="WebMotors listing/search URL")
    parser.add_argument("--proxy", default=None, help="Optional proxy URL")
    parser.add_argument("--wait-until", default="networkidle", choices=["load", "domcontentloaded", "networkidle", "commit"])
    parser.add_argument("--save-artifacts", action="store_true", help="Enable runtime artifact capture (HTML + metadata).")
    args = parser.parse_args()

    extra = {"webmotors_debug_capture": bool(args.save_artifacts)}
    ctx = ScrapeContext(
        source="webmotors",
        proxy_server=args.proxy,
        browser_wait_until=args.wait_until,
        extra=extra,
    )

    try:
        out = scrape_webmotors(args.url, ctx)
        print(json.dumps({"ok": True, "items": len(out), "message": "scrape succeeded"}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc), "hint": "If --save-artifacts was used, check runtime webmotors debug dir."}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
