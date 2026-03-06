from __future__ import annotations

from time import perf_counter
from typing import Any

from app.sources.ad_quality import enforce_ads_contract
from app.sources.contract import ResultMetadata
from app.sources.normalize import normalize_many


def adapt_v1(source: str, raw_items: list[dict[str, Any]] | None, *, duration_ms: int | None = None) -> tuple[list, ResultMetadata]:
    t0 = perf_counter()
    rows = raw_items or []
    ads = normalize_many(source, rows)
    ads, quality_summary = enforce_ads_contract(ads)
    took = duration_ms if duration_ms is not None else int((perf_counter() - t0) * 1000)
    metadata = ResultMetadata(
        source=source,
        impl="v1",
        duration_ms=int(took),
        raw_count=len(rows),
        normalized_count=len(ads),
        reason_buckets={
            "quality_warning": int(quality_summary.get("warning", 0)),
            "quality_critical": int(quality_summary.get("critical", 0)),
        },
    )
    return ads, metadata
