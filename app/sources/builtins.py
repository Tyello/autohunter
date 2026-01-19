"""Built-in source plugins.

Add new sources here (or in your own module imported at startup).

Rules:
- `name` must match the value stored in `car_listings.source` and used by
  `allowed_sources_for_wishlist`.
- `enabled_setting`/`sched_minutes_setting`/`cooldown_minutes_setting` refer to
  attributes in `app/core/settings.py`.
"""

from app.services.search_urls_service import (
    ml_url,
    olx_url,
    chavesnamao_url,
    webmotors_url,
    gogarage_url,
)

from app.scrapers.mercadolivre import scrape_mercadolivre
from app.scrapers.olx import scrape_olx
from app.scrapers.chavesnamao import scrape_chavesnamao
from app.scrapers.webmotors import scrape_webmotors
from app.scrapers.gogarage import scrape_gogarage

from .registry import register_source
from .types import SourcePlugin


# Mercado Livre: API/HTML; always enabled in the MVP.
register_source(
    SourcePlugin(
        name="mercadolivre",
        build_url=ml_url,
        scrape=scrape_mercadolivre,
        enabled_setting=None,
        sched_minutes_setting="sched_ml_minutes",
        cooldown_minutes_setting=None,
        supports_manual_search=True,
        supports_wishlist_monitoring=True,
        fetch_mode="browser",
    )
)


# OLX: scraping leve, pode ter bloqueio.
register_source(
    SourcePlugin(
        name="olx",
        build_url=olx_url,
        scrape=scrape_olx,
        enabled_setting="enable_olx",
        sched_minutes_setting="sched_olx_minutes",
        cooldown_minutes_setting="olx_cooldown_minutes",
        supports_manual_search=True,
        supports_wishlist_monitoring=True,
        fetch_mode="browser",
    )
)


# Chaves na Mão: SSR, barato.
register_source(
    SourcePlugin(
        name="chavesnamao",
        build_url=chavesnamao_url,
        scrape=scrape_chavesnamao,
        enabled_setting="enable_chavesnamao",
        sched_minutes_setting="sched_chavesnamao_minutes",
        cooldown_minutes_setting="chavesnamao_cooldown_minutes",
        supports_manual_search=True,
        supports_wishlist_monitoring=True,
    )
)


# Webmotors: SPA/JS-heavy. Placeholder (scrape=scrape_webmotors) até implementar via API/headless.
register_source(
    SourcePlugin(
        name="webmotors",
        build_url=webmotors_url,
        scrape=scrape_webmotors,
        enabled_setting="enable_webmotors",
        sched_minutes_setting="sched_webmotors_minutes",
        cooldown_minutes_setting="webmotors_cooldown_minutes",
        supports_manual_search=True,
        supports_wishlist_monitoring=True,
        fetch_mode="browser",
    )
)


# GoGarage: SPA/JS-heavy. Placeholder.
register_source(
    SourcePlugin(
        name="gogarage",
        build_url=gogarage_url,
        scrape=scrape_gogarage,
        enabled_setting="enable_gogarage",
        sched_minutes_setting="sched_gogarage_minutes",
        cooldown_minutes_setting="gogarage_cooldown_minutes",
        supports_manual_search=True,
        supports_wishlist_monitoring=True,
        fetch_mode="browser",
    )
)
