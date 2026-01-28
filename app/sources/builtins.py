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
    mobiauto_url,
    kavak_url,
    facebook_marketplace_url,
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
        rate_limit_seconds_setting="rate_limit_mercadolivre_seconds",
        supports_manual_search=True,
        supports_wishlist_monitoring=True,
        fetch_mode="http",
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
        rate_limit_seconds_setting="rate_limit_olx_seconds",
        supports_manual_search=True,
        supports_wishlist_monitoring=True,
        # Primário via HTTP; pode cair para browser internamente quando bloqueado.
        fetch_mode="http",
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
        rate_limit_seconds_setting="rate_limit_chavesnamao_seconds",
        supports_manual_search=True,
        supports_wishlist_monitoring=True,
    )
)


# Webmotors: HTTP-first via endpoint XHR (sem Playwright como padrão).
register_source(
    SourcePlugin(
        name="webmotors",
        build_url=webmotors_url,
        scrape=scrape_webmotors,
        enabled_setting="enable_webmotors",
        sched_minutes_setting="sched_webmotors_minutes",
        cooldown_minutes_setting="webmotors_cooldown_minutes",
        rate_limit_seconds_setting="rate_limit_webmotors_seconds",
        supports_manual_search=True,
        supports_wishlist_monitoring=True,
        fetch_mode="http",
    )
)


# GoGarage: HTTP-first (HTML/JSON-LD) com fallback opcional.
register_source(
    SourcePlugin(
        name="gogarage",
        build_url=gogarage_url,
        scrape=scrape_gogarage,
        enabled_setting="enable_gogarage",
        sched_minutes_setting="sched_gogarage_minutes",
        cooldown_minutes_setting="gogarage_cooldown_minutes",
        rate_limit_seconds_setting="rate_limit_gogarage_seconds",
        supports_manual_search=True,
        supports_wishlist_monitoring=True,
        fetch_mode="http",
    )
)


# --- Future sources (placeholders) ---
# Objetivo: aparecerem no /admin sources para gestão/roadmap,
# mas sem rodar jobs nem entrar na busca manual até existir scraper.

register_source(
    SourcePlugin(
        name="mobiauto",
        build_url=mobiauto_url,
        scrape=None,
        enabled_setting="enable_mobiauto",
        sched_minutes_setting="sched_mobiauto_minutes",
        cooldown_minutes_setting="mobiauto_cooldown_minutes",
        rate_limit_seconds_setting="rate_limit_mobiauto_seconds",
        supports_manual_search=False,
        supports_wishlist_monitoring=False,
        fetch_mode="http",
    )
)

register_source(
    SourcePlugin(
        name="kavak",
        build_url=kavak_url,
        scrape=None,
        enabled_setting="enable_kavak",
        sched_minutes_setting="sched_kavak_minutes",
        cooldown_minutes_setting="kavak_cooldown_minutes",
        rate_limit_seconds_setting="rate_limit_kavak_seconds",
        supports_manual_search=False,
        supports_wishlist_monitoring=False,
        fetch_mode="http",
    )
)

register_source(
    SourcePlugin(
        name="facebook_marketplace",
        build_url=facebook_marketplace_url,
        scrape=None,
        enabled_setting="enable_facebook_marketplace",
        sched_minutes_setting="sched_facebook_marketplace_minutes",
        cooldown_minutes_setting="facebook_marketplace_cooldown_minutes",
        rate_limit_seconds_setting="rate_limit_facebook_marketplace_seconds",
        supports_manual_search=False,
        supports_wishlist_monitoring=False,
        fetch_mode="browser",
    )
)
