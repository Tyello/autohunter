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
    icarros_url,
    mobiauto_url,
    kavak_url,
    facebook_marketplace_url,
    turboclass_url,
)

from app.scrapers.mercadolivre import scrape_mercadolivre
from app.scrapers.olx import scrape_olx
from app.scrapers.chavesnamao import scrape_chavesnamao
from app.scrapers.webmotors import scrape_webmotors
from app.scrapers.gogarage import scrape_gogarage
from app.scrapers.facebook_marketplace import scrape_facebook_marketplace
from app.scrapers.icarros import scrape_icarros
from app.scrapers.kavak import scrape_kavak
from app.scrapers.mobiauto import scrape_mobiauto
from app.scrapers.turboclass import scrape_turboclass

from .registry import register_source
from .types import SourcePlugin, ScrapeContext


def _scrape_chavesnamao(search_url: str, ctx: ScrapeContext) -> list[dict]:
    return scrape_chavesnamao(search_url, ctx=ctx)


def _scrape_turboclass(search_url: str, ctx: ScrapeContext) -> list[dict]:
    # NOTE: plugin.scrape é sempre chamado como (search_url, ctx).
    # O scraper TurboClass aceita (search_url, limit=..., ctx=...).
    return scrape_turboclass(search_url, ctx=ctx)


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
        # Browser fallback is a safety net (rarely used), but prevents the source
        # from silently dying on anti-bot waves.
        default_browser_fallback_enabled=True,
        default_extra={
            "operational_role": "primary",
            "http_connect_timeout_s": 5,
            "http_read_timeout_s": 20,
            "http_min_delay_ms": 120,
            "http_max_delay_ms": 420,
            "browser_timeout_ms": 45000,
            "browser_wait_until": "domcontentloaded",
        },
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
        default_browser_fallback_enabled=True,
        default_extra={
            "operational_role": "primary",
            "http_connect_timeout_s": 6,
            "http_read_timeout_s": 22,
            "http_min_delay_ms": 600,
            "http_max_delay_ms": 1500,
        },
    )
)


# Chaves na Mão: SSR, barato.
register_source(
    SourcePlugin(
        name="chavesnamao",
        build_url=chavesnamao_url,
        scrape=_scrape_chavesnamao,
        enabled_setting="enable_chavesnamao",
        sched_minutes_setting="sched_chavesnamao_minutes",
        cooldown_minutes_setting="chavesnamao_cooldown_minutes",
        rate_limit_seconds_setting="rate_limit_chavesnamao_seconds",
        supports_manual_search=True,
        supports_wishlist_monitoring=True,
        # Prioriza Playwright para estabilidade (evita SSR/anti-bot variar por região).
        fetch_mode="browser",
        default_force_browser=True,
        default_browser_fallback_enabled=True,
        default_extra={
            "operational_role": "primary",
            "http_connect_timeout_s": 5,
            "http_read_timeout_s": 20,
            "http_min_delay_ms": 180,
            "http_max_delay_ms": 650,
            "browser_timeout_ms": 35000,
            "browser_wait_until": "domcontentloaded",
        },
    )
)


# Webmotors: tipicamente bloqueia HTTP (challenge com HTTP 200).
# Browser-first capturando XHR JSON (Playwright) é o caminho mais estável.
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
        fetch_mode="browser",
        default_sched_minutes=90,
        default_browser_fallback_enabled=True,
        default_force_browser=True,
        default_extra={
            "operational_role": "deprioritized",
            "browser_block_resources": False,
            "webmotors_curl_cffi_enabled": False,
            "webmotors_curl_cffi_impersonate": "chrome",
        },
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
        # GoGarage é JS-heavy; browser-first elimina HTML placeholder que quebra parsing/matching.
        fetch_mode="browser",
        default_force_browser=True,
        default_browser_fallback_enabled=True,
        default_extra={
            "operational_role": "fragile",
            "browser_timeout_ms": 45000,
            "browser_wait_until": "domcontentloaded",
        },
    )
)

register_source(
    SourcePlugin(
        name="icarros",
        build_url=icarros_url,
        scrape=scrape_icarros,
        enabled_setting="enable_icarros",
        sched_minutes_setting="sched_icarros_minutes",
        cooldown_minutes_setting="icarros_cooldown_minutes",
        rate_limit_seconds_setting="rate_limit_icarros_seconds",
        supports_manual_search=True,
        supports_wishlist_monitoring=True,
        fetch_mode="browser",
        default_force_browser=True,
        default_browser_fallback_enabled=True,
        default_extra={
            "operational_role": "fragile",
            "browser_timeout_ms": 45000,
            "browser_wait_until": "domcontentloaded",
            "browser_block_resources": False,
        },
    )
)

register_source(
    SourcePlugin(
        name="mobiauto",
        build_url=mobiauto_url,
        scrape=scrape_mobiauto,
        enabled_setting="enable_mobiauto",
        sched_minutes_setting="sched_mobiauto_minutes",
        cooldown_minutes_setting="mobiauto_cooldown_minutes",
        rate_limit_seconds_setting="rate_limit_mobiauto_seconds",
        supports_manual_search=True,
        supports_wishlist_monitoring=True,
        # JS-heavy + bloqueios: browser-first.
        fetch_mode="browser",
        default_force_browser=True,
        default_browser_fallback_enabled=True,
        default_extra={
            "operational_role": "fragile",
            "browser_timeout_ms": 45000,
            "browser_wait_until": "domcontentloaded",
            "browser_block_resources": False,
        },
    )
)

register_source(
    SourcePlugin(
        name="kavak",
        build_url=kavak_url,
        scrape=scrape_kavak,
        enabled_setting="enable_kavak",
        sched_minutes_setting="sched_kavak_minutes",
        cooldown_minutes_setting="kavak_cooldown_minutes",
        rate_limit_seconds_setting="rate_limit_kavak_seconds",
        supports_manual_search=True,
        supports_wishlist_monitoring=True,
        fetch_mode="browser",
        default_force_browser=True,
        default_extra={
            "operational_role": "experimental",
        },
    )
)

register_source(
    SourcePlugin(
        name="facebook_marketplace",
        build_url=facebook_marketplace_url,
        scrape=scrape_facebook_marketplace,
        enabled_setting="enable_facebook_marketplace",
        sched_minutes_setting="sched_facebook_marketplace_minutes",
        cooldown_minutes_setting="facebook_marketplace_cooldown_minutes",
        rate_limit_seconds_setting="rate_limit_facebook_marketplace_seconds",
        supports_manual_search=False,
        supports_wishlist_monitoring=True,
        fetch_mode="browser",
        default_force_browser=True,
        default_cooldown_minutes=180,
        default_extra={
            "operational_role": "experimental",
            "browser_block_resources": False,
        },
    )
)


# TurboClass: SSR estável e barato. Começa desabilitado por default.
register_source(
    SourcePlugin(
        name="turboclass",
        build_url=turboclass_url,
        scrape=_scrape_turboclass,
        enabled_setting=None,
        sched_minutes_setting=None,
        cooldown_minutes_setting=None,
        rate_limit_seconds_setting=None,
        supports_manual_search=True,
        supports_wishlist_monitoring=True,
        fetch_mode="http",
        default_enabled=False,
        default_sched_minutes=90,
        default_browser_fallback_enabled=True,
        default_extra={
            "operational_role": "experimental",
            "http_connect_timeout_s": 5,
            "http_read_timeout_s": 20,
            "http_min_delay_ms": 220,
            "http_max_delay_ms": 650,
            "browser_timeout_ms": 35000,
            "browser_wait_until": "domcontentloaded",
            # Incremental ingest (per URL): cuts work on 24/7 runs.
            "incremental_enabled": True,
            # cap new ingested items per URL-run (still matches on full set)
            "incremental_max_new": 120,
        },
    )
)
