from __future__ import annotations

from typing import Any, Callable

from app.scrapers.scraper_base.scraper import BaseScraper
from app.scrapers.source_contract import ResultMetadata, SourceError, SourceResult, timed_normalize
from app.sources.types import ScrapeContext


def run_v1_adapter(
    source: str,
    scrape_fn: Callable[..., list[dict[str, Any]]],
    search_url: str,
    ctx: ScrapeContext,
) -> SourceResult:
    try:
        try:
            raw = scrape_fn(search_url, ctx=ctx)
        except TypeError:
            raw = scrape_fn(search_url, ctx)
        return timed_normalize(source, raw or [], impl="v1", raw_count=len(raw or []))
    except Exception as exc:
        return SourceResult(
            ads=[],
            metadata=ResultMetadata(source=source, impl="v1", duration_ms=0, raw_count=0, normalized_count=0, partial_failure=True),
            error=SourceError(code="v1_scrape_error", message=str(exc), retriable=True),
        )


def run_v2_adapter(
    source: str,
    scraper: BaseScraper,
    search_url: str,
    ctx: ScrapeContext,
) -> SourceResult:
    try:
        result = scraper.scrape(search_url, ctx)
        normalized = timed_normalize(source, result.listings or [], impl="v2", raw_count=len(result.listings or []))
        return SourceResult(
            ads=normalized.ads,
            metadata=ResultMetadata(
                source=source,
                impl="v2",
                duration_ms=normalized.metadata.duration_ms,
                raw_count=normalized.metadata.raw_count,
                normalized_count=normalized.metadata.normalized_count,
                blocked=bool(result.blocked),
                partial_failure=bool(result.partial_failure),
                warnings_count=len(result.warnings or []),
            ),
            error=normalized.error,
        )
    except Exception as exc:
        return SourceResult(
            ads=[],
            metadata=ResultMetadata(source=source, impl="v2", duration_ms=0, raw_count=0, normalized_count=0, partial_failure=True),
            error=SourceError(code="v2_scrape_error", message=str(exc), retriable=True),
        )
