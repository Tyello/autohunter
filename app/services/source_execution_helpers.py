from __future__ import annotations

from typing import Any, Callable

from app.sources.adapters.v1 import adapt_v1
from app.sources.adapters.v2 import adapt_v2
from app.sources.dual_run import execute_dual_run


def build_scrape_dispatch(
    *,
    src: str,
    flags,
    plugin,
    v2_scraper,
    ad_to_listing: Callable[[Any], dict[str, Any]],
):
    """Build scraper dispatch preserving v1/v2/dual runtime behavior."""

    def _scrape_dispatch(search_url: str, ctx):
        if flags.impl == "v2" and v2_scraper is not None:
            result = v2_scraper.scrape(search_url, ctx)
            ads, meta = adapt_v2(src, result)
            object.__setattr__(
                ctx,
                "_last_adapter_meta",
                {
                    "impl": "v2",
                    "raw_count": int(getattr(meta, "raw_count", 0) or 0),
                    "normalized_count": int(getattr(meta, "normalized_count", 0) or 0),
                    "partial_failure": bool(getattr(meta, "partial_failure", False)),
                    "blocked": bool(getattr(meta, "blocked", False)),
                },
            )
            return [ad_to_listing(ad) for ad in ads if ad.external_id]

        if flags.impl == "dual" and v2_scraper is not None:
            chosen, report = execute_dual_run(
                source=src,
                search_url=search_url,
                ctx=ctx,
                v1_scrape_fn=plugin.scrape,
                v2_scraper=v2_scraper,
                flags=flags,
            )
            object.__setattr__(ctx, "_dual_run_summary", report.get("comparison") or {})
            ads, meta = adapt_v1(src, chosen)
            object.__setattr__(
                ctx,
                "_last_adapter_meta",
                {
                    "impl": "dual_v1",
                    "raw_count": int(getattr(meta, "raw_count", 0) or 0),
                    "normalized_count": int(getattr(meta, "normalized_count", 0) or 0),
                    "partial_failure": False,
                    "blocked": False,
                },
            )
            return [ad_to_listing(ad) for ad in ads if ad.external_id]

        raw = plugin.scrape(search_url, ctx=ctx)
        ads, meta = adapt_v1(src, raw)
        object.__setattr__(
            ctx,
            "_last_adapter_meta",
            {
                "impl": "v1",
                "raw_count": int(getattr(meta, "raw_count", 0) or 0),
                "normalized_count": int(getattr(meta, "normalized_count", 0) or 0),
                "partial_failure": False,
                "blocked": False,
            },
        )
        return [ad_to_listing(ad) for ad in ads if ad.external_id]

    return _scrape_dispatch


def build_run_payload(
    *,
    run_summary: dict[str, Any],
    run_reason: str,
    hybrid_browser_used: bool,
    hybrid_blocked: bool,
    hybrid_blocked_status: int | None,
    thumb_present: int | None = None,
    thumb_rate: float | None = None,
    backoff_minutes: int | None = None,
    retry_minutes: int | None = None,
    is_bug: bool | None = None,
    webmotors_diag: dict[str, Any] | None = None,
    dual_report: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "hybrid_browser_used": bool(hybrid_browser_used),
        "hybrid_blocked": bool(hybrid_blocked),
        "hybrid_blocked_status": hybrid_blocked_status,
        "run_summary": run_summary,
        "run_reason": run_reason,
    }
    if thumb_present is not None:
        payload["thumb_present"] = int(thumb_present)
    if thumb_rate is not None:
        payload["thumb_rate"] = float(thumb_rate)
    if backoff_minutes is not None:
        payload["backoff_minutes"] = int(backoff_minutes)
    if retry_minutes is not None:
        payload["retry_minutes"] = int(retry_minutes)
    if is_bug is not None:
        payload["is_bug"] = bool(is_bug)
    if webmotors_diag is not None:
        payload["webmotors_diag"] = webmotors_diag
    if dual_report:
        payload["dual_report"] = dual_report
    return payload
