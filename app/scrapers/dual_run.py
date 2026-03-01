from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.scrapers.source_adapters import run_v1_adapter, run_v2_adapter
from app.scrapers.source_contract import SourceResult
from app.scrapers.scraper_base.scraper import BaseScraper
from app.sources.types import ScrapeContext

_REPORT_DIR = Path("var/dual_run_reports")


def _ad_index(result: SourceResult) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for ad in result.ads:
        if not ad.external_id:
            continue
        out[ad.external_id] = ad.to_listing()
    return out


def compare_results(v1: SourceResult, v2: SourceResult, *, max_diffs: int = 20) -> dict[str, Any]:
    i1 = _ad_index(v1)
    i2 = _ad_index(v2)
    k1 = set(i1.keys())
    k2 = set(i2.keys())

    only_v1 = sorted(k1 - k2)
    only_v2 = sorted(k2 - k1)
    shared = sorted(k1 & k2)

    diffs: list[dict[str, Any]] = []
    for key in shared:
        if len(diffs) >= max_diffs:
            break
        a = i1[key]
        b = i2[key]
        changed: dict[str, Any] = {}
        for field in ("price", "title", "location", "thumbnail_url"):
            if a.get(field) != b.get(field):
                changed[field] = {"v1": a.get(field), "v2": b.get(field)}
        if changed:
            diffs.append({"external_id": key, "changed": changed})

    return {
        "v1_count": len(k1),
        "v2_count": len(k2),
        "intersection": len(shared),
        "only_v1_count": len(only_v1),
        "only_v2_count": len(only_v2),
        "only_v1_sample": only_v1[:10],
        "only_v2_sample": only_v2[:10],
        "field_diffs": diffs,
    }


def persist_dual_run_report(source: str, payload: dict[str, Any]) -> str:
    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = _REPORT_DIR / f"{source}.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    return str(path)


def run_with_dual_mode(
    *,
    source: str,
    search_url: str,
    ctx: ScrapeContext,
    v1_scrape_fn,
    v2_scraper: BaseScraper | None,
    dual_mode: str,
) -> list[dict[str, Any]]:
    mode = (dual_mode or "v1_primary").strip().lower()
    v1 = run_v1_adapter(source, v1_scrape_fn, search_url, ctx)
    v2 = run_v2_adapter(source, v2_scraper, search_url, ctx) if v2_scraper else None

    primary = "v1"
    chosen = v1
    comp: dict[str, Any] | None = None
    if v2 is not None:
        comp = compare_results(v1, v2)
        if mode in {"v2_primary", "prefer_v2"}:
            primary = "v2"
            chosen = v2

    report = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "search_url": search_url,
        "dual_mode": mode,
        "primary": primary,
        "v1": {"meta": asdict(v1.metadata), "error": asdict(v1.error) if v1.error else None},
        "v2": ({"meta": asdict(v2.metadata), "error": asdict(v2.error) if v2 and v2.error else None} if v2 else None),
        "comparison": comp,
    }
    report_path = persist_dual_run_report(source, report)
    object.__setattr__(ctx, "_dual_run_report_path", report_path)
    object.__setattr__(ctx, "_dual_run_summary", comp or {})

    return [ad.to_listing() for ad in chosen.ads]
