from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        extra='ignore',
        case_sensitive=False,
    )

    database_url: str
    telegram_bot_token: str | None = None
    autohunter_admins: str | None = None

    default_user_timezone: str = 'America/Sao_Paulo'

    # Feature flags
    enable_scheduler_in_api: bool = False

    # Per-source proxies (optional)
    source_proxy_olx: str | None = None
    source_proxy_webmotors: str | None = None
    source_proxy_gogarage: str | None = None
    source_proxy_kavak: str | None = None
    source_proxy_mobiauto: str | None = None
    source_proxy_icarros: str | None = None
    source_proxy_facebook_marketplace: str | None = None


    # Per-source rate limits (seconds). 0 disables throttling.
    rate_limit_olx_seconds: int = 20
    rate_limit_webmotors_seconds: int = 10
    rate_limit_gogarage_seconds: int = 10
    rate_limit_chavesnamao_seconds: int = 5
    rate_limit_mercadolivre_seconds: int = 0
    rate_limit_kavak_seconds: int = 30
    rate_limit_mobiauto_seconds: int = 10
    rate_limit_icarros_seconds: int = 20
    rate_limit_facebook_marketplace_seconds: int = 90


    # OLX
    enable_olx: bool = True
    olx_cooldown_minutes: int = 120
    enable_olx_browser_fallback: bool = True
    # Force OLX scraping via Playwright (recommended when OLX returns 403/Cloudflare to HTTP clients)
    olx_force_browser: bool = False

    # Chaves na Mao
    enable_chavesnamao: bool = True
    chavesnamao_cooldown_minutes: int = 30

    # SPA sources (usually require browser/headless or partner API)
    enable_webmotors: bool = True
    webmotors_cooldown_minutes: int = 180
    enable_gogarage: bool = True
    gogarage_cooldown_minutes: int = 180

    # Additional sources (mostly browser-heavy / anti-bot)
    enable_kavak: bool = True
    kavak_cooldown_minutes: int = 240
    enable_mobiauto: bool = True
    mobiauto_cooldown_minutes: int = 120
    enable_icarros: bool = True
    icarros_cooldown_minutes: int = 240
    enable_facebook_marketplace: bool = True
    facebook_marketplace_cooldown_minutes: int = 360

    # Playwright / Browser mode
    enable_playwright: bool = True
    playwright_headless: bool = True

    # Cookie/session stickiness (Playwright)
    playwright_storage_dir: str = '.data/playwright'


    # Playwright queue & dedupe (scaling)
    # - queue_max_jobs: hard cap to avoid RAM blowups on Raspberry Pi
    # - dedupe_inflight: if the same (url, source, proxy) is requested while in-flight, join instead of enqueue
    # - cache_ttl_seconds: short TTL to collapse bursts (manual search / multiple users) without serving stale results for long
    # - cache_max_entries: keep small; browser HTML can be heavy
    playwright_queue_max_jobs: int = 25
    playwright_dedupe_inflight: bool = True
    playwright_cache_ttl_seconds: int = 30
    playwright_cache_max_entries: int = 16

    default_alert_limit: int = 30

    # Scheduler tuning (DEV)
    sched_ml_minutes: int = 30
    sched_olx_minutes: int = 60
    sched_chavesnamao_minutes: int = 60
    sched_webmotors_minutes: int = 180
    sched_gogarage_minutes: int = 180
    sched_kavak_minutes: int = 360
    sched_mobiauto_minutes: int = 120
    sched_icarros_minutes: int = 360
    sched_facebook_marketplace_minutes: int = 720
    sched_sender_seconds: int = 60
    # APScheduler thread pool. For Raspberry Pi 3, 2-4 is usually safer.
    scheduler_workers: int = 4

    # Backoff automatico (protects product and helps avoid bans)
    source_backoff_max_minutes: int = 720
    source_backoff_jitter_seconds: int = 20

    telegram_text_max: int = 4000
    safe_chunk: int = 3800

settings = Settings()
