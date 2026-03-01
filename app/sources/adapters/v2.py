from __future__ import annotations

from time import perf_counter
from typing import Any

from app.scrapers.scraper_base.scraper import ScraperResult
from app.sources.contract import ResultMetadata
from app.sources.normalize import normalize_many


def adapt_v2(source: str, result: ScraperResult, *, duration_ms: int | None = None) -> tuple[list, ResultMetadata]:
    t0 = perf_counter()
    rows: list[dict[str, Any]] = list(result.listings or [])
    ads = normalize_many(source, rows)
    took = duration_ms if duration_ms is not None else int((perf_counter() - t0) * 1000)
    metadata = ResultMetadata(
        source=source,
        impl="v2",
        duration_ms=int(took),
        raw_count=len(rows),
        normalized_count=len(ads),
        blocked=bool(result.blocked),
        partial_failure=bool(result.partial_failure),
        warnings_count=len(result.warnings or []),
    )
    return ads, metadata
