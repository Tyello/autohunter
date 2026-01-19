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

    # Per-source rate limits (seconds). 0 disables throttling.
    rate_limit_olx_seconds: int = 20
    rate_limit_webmotors_seconds: int = 10
    rate_limit_gogarage_seconds: int = 10
    rate_limit_chavesnamao_seconds: int = 5
    rate_limit_mercadolivre_seconds: int = 0

    # OLX
    enable_olx: bool = False
    olx_cooldown_minutes: int = 60
    enable_olx_browser_fallback: bool = True

    # Chaves na Mao
    enable_chavesnamao: bool = True
    chavesnamao_cooldown_minutes: int = 30

    # SPA sources (usually require browser/headless or partner API)
    enable_webmotors: bool = False
    webmotors_cooldown_minutes: int = 180
    enable_gogarage: bool = False
    gogarage_cooldown_minutes: int = 180

    # Playwright / Browser mode
    enable_playwright: bool = False
    playwright_headless: bool = True

    # Cookie/session stickiness (Playwright)
    playwright_storage_dir: str = '.data/playwright'

    default_alert_limit: int = 30

    # Scheduler tuning (DEV)
    sched_ml_minutes: int = 30
    sched_olx_minutes: int = 30
    sched_chavesnamao_minutes: int = 60
    sched_webmotors_minutes: int = 180
    sched_gogarage_minutes: int = 180
    sched_sender_seconds: int = 60
    # APScheduler thread pool. For Raspberry Pi 3, 2-4 is usually safer.
    scheduler_workers: int = 4

    # Backoff automatico (protects product and helps avoid bans)
    source_backoff_max_minutes: int = 720
    source_backoff_jitter_seconds: int = 20


settings = Settings()
