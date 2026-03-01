from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from app.scrapers.scraper_base.scraper import BaseScraper
from app.sources.adapters.v1 import adapt_v1
from app.sources.adapters.v2 import adapt_v2
from app.sources.compare import compare_ads
from app.sources.flags import SourceImplFlags
from app.sources.types import ScrapeContext


def execute_dual_run(
    *,
    source: str,
    search_url: str,
    ctx: ScrapeContext,
    v1_scrape_fn,
    v2_scraper: BaseScraper,
    flags: SourceImplFlags,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    raw_v1 = v1_scrape_fn(search_url, ctx=ctx)
    v1_ads, v1_meta = adapt_v1(source, raw_v1)

    v2_result = v2_scraper.scrape(search_url, ctx)
    v2_ads, v2_meta = adapt_v2(source, v2_result)

    report = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "dual_mode": flags.dual_mode,
        "v1": asdict(v1_meta),
        "v2": asdict(v2_meta),
        "comparison": compare_ads(v1_ads, v2_ads, thresholds=flags.compare_cfg),
    }

    chosen = raw_v1
    if flags.dual_mode == "compare_and_use_v2":
        chosen = [
            {
                "source": ad.source,
                "external_id": ad.source_listing_id,
                "url": ad.url,
                "title": ad.title,
                "price": ad.price,
                "currency": ad.currency,
                "location": ", ".join([x for x in [ad.city, ad.uf] if x]) or None,
                "year": ad.year,
                "mileage_km": ad.km,
                "images_count": ad.images_count,
            }
            for ad in v2_ads
        ]

    return chosen or [], report
