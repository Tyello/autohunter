from __future__ import annotations

from typing import Any, Callable

from app.core.settings import settings
from app.scrapers.base import FetchBlocked
from app.sources.adapters.v1 import adapt_v1
from app.sources.adapters.v2 import adapt_v2
from app.sources.dual_run import execute_dual_run


CRITICAL_LISTING_FIELDS = ("year", "mileage_km", "price")


def compute_field_coverage(listings: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Fill rate per critical field for a scrape's normalized listings.

    Mirrors the existing thumb_present/thumb_rate pattern so it can flow
    through the same run payload/alerting plumbing (see build_run_payload,
    operational_alerts_service).
    """
    total = len(listings or [])
    coverage: dict[str, dict[str, Any]] = {}
    for field in CRITICAL_LISTING_FIELDS:
        present = sum(1 for it in (listings or []) if (it or {}).get(field) is not None)
        coverage[field] = {
            "present": present,
            "rate": (present / total) if total else 0.0,
        }
    return coverage


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
        canary_guarded_v2 = (
            src == "mercadolivre"
            and bool(getattr(flags, "canary_v2_enabled", False))
            and bool(getattr(settings, "enable_playwright", False))
            and bool(getattr(ctx, "browser_fallback_enabled", False))
        )
        use_v2 = flags.impl == "v2" or canary_guarded_v2

        if use_v2 and v2_scraper is not None:
            runtime_impl = "v2_canary" if canary_guarded_v2 and flags.impl != "v2" else "v2"
            object.__setattr__(
                ctx,
                "_last_adapter_meta",
                {
                    "impl": runtime_impl,
                    "raw_count": 0,
                    "normalized_count": 0,
                    "partial_failure": False,
                    "blocked": False,
                    "attempted": True,
                },
            )
            result = v2_scraper.scrape(search_url, ctx)
            ads, meta = adapt_v2(src, result)
            object.__setattr__(
                ctx,
                "_last_adapter_meta",
                {
                    "impl": runtime_impl,
                    "raw_count": int(getattr(meta, "raw_count", 0) or 0),
                    "normalized_count": int(getattr(meta, "normalized_count", 0) or 0),
                    "partial_failure": bool(getattr(meta, "partial_failure", False)),
                    "blocked": bool(getattr(meta, "blocked", False)),
                    "attempted": True,
                },
            )
            if bool(getattr(meta, "blocked", False)):
                # The v2 pipeline (BaseScraper.scrape) swallows FetchBlocked internally
                # and reports it as `result.blocked` instead of raising, so it never
                # reaches the v1-era backoff/alerting path below (which only reacts to
                # a raised FetchBlocked or `ok=False`). Re-raise here to plug back into
                # that existing machinery instead of silently reporting found=0.
                detail = result.metrics.fetch_error or (result.warnings[0] if result.warnings else "blocked")
                raise FetchBlocked(200, search_url, reason=detail)
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


_ANTIBOT_MAX_SHADOW_URLS = 5


def merge_antibot_diag(acc: dict[str, Any], res: dict[str, Any]) -> None:
    """Accumulate the antibot fields of one scrape result (see jobs._ctx_fetch_diag)."""
    acc["detector_calls"] = int(acc.get("detector_calls", 0)) + int(res.get("antibot_detector_calls") or 0)
    acc["detector_ms"] = float(acc.get("detector_ms", 0.0)) + float(res.get("antibot_detector_ms") or 0.0)
    shadow = int(res.get("antibot_shadow_count") or 0)
    acc["shadow_count"] = int(acc.get("shadow_count", 0)) + shadow
    if shadow:
        acc["shadow_reason"] = res.get("antibot_shadow_tier3")
        url = res.get("antibot_shadow_url")
        urls = acc.setdefault("shadow_urls", [])
        if url and url not in urls and len(urls) < _ANTIBOT_MAX_SHADOW_URLS:
            urls.append(url)
    reason = res.get("hybrid_block_reason")
    if reason:
        reasons = acc.setdefault("block_reasons", {})
        reasons[reason] = int(reasons.get(reason, 0)) + 1


def antibot_run_diag(acc: dict[str, Any]) -> dict[str, Any] | None:
    """Compact antibot summary for SourceRun.payload; None when there is nothing to report."""
    calls = int(acc.get("detector_calls") or acc.get("antibot_detector_calls") or 0)
    ms = float(acc.get("detector_ms") if acc.get("detector_ms") is not None else acc.get("antibot_detector_ms") or 0.0)
    shadow = int(acc.get("shadow_count") or acc.get("antibot_shadow_count") or 0)
    reasons = acc.get("block_reasons") or {}
    if not (calls or shadow or reasons):
        return None
    out: dict[str, Any] = {
        "detector_calls": calls,
        "detector_ms": round(ms, 3),
        "detector_ms_avg": round(ms / calls, 3) if calls else 0.0,
        "shadow_count": shadow,
    }
    if shadow:
        out["shadow_reason"] = acc.get("shadow_reason")
        out["shadow_urls"] = list(acc.get("shadow_urls") or [])
    if reasons:
        out["block_reasons"] = dict(reasons)
    return out


def build_run_payload(
    *,
    run_summary: dict[str, Any],
    run_reason: str,
    hybrid_browser_used: bool,
    hybrid_blocked: bool,
    hybrid_blocked_status: int | None,
    thumb_present: int | None = None,
    thumb_rate: float | None = None,
    field_coverage: dict[str, Any] | None = None,
    backoff_minutes: int | None = None,
    retry_minutes: int | None = None,
    is_bug: bool | None = None,
    webmotors_diag: dict[str, Any] | None = None,
    dual_report: str | None = None,
    runtime_impl: str | None = None,
    adapter_meta: dict[str, Any] | None = None,
    antibot: dict[str, Any] | None = None,
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
    if isinstance(field_coverage, dict):
        payload["field_coverage"] = field_coverage
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
    if runtime_impl:
        payload["runtime_impl"] = str(runtime_impl)
    if isinstance(antibot, dict) and antibot:
        payload["antibot"] = antibot
    if isinstance(adapter_meta, dict):
        payload["adapter_meta"] = adapter_meta
    return payload
