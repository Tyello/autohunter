from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        extra='forbid',
    )

    database_url: str
    telegram_bot_token: str | None = None
    autohunter_admins: str | None = None

    default_user_timezone: str = 'America/Sao_Paulo'

    # Feature flags
    enable_scheduler_in_api: bool = False

    # OLX
    enable_olx: bool = False
    olx_cooldown_minutes: int = 60
    enable_olx_browser_fallback: bool = True

    # Chaves na Mão
    enable_chavesnamao: bool = True
    chavesnamao_cooldown_minutes: int = 30

    # Fontes SPA (normalmente exigem browser/headless ou API parceira)
    enable_webmotors: bool = False
    webmotors_cooldown_minutes: int = 180
    enable_gogarage: bool = False
    gogarage_cooldown_minutes: int = 180

    # Playwright / Browser mode
    enable_playwright: bool = False
    playwright_headless: bool = True

    default_alert_limit: int = 30

    # Scheduler tuning (DEV)
    sched_ml_minutes: int = 30
    sched_olx_minutes: int = 30
    sched_chavesnamao_minutes: int = 60
    sched_webmotors_minutes: int = 180
    sched_gogarage_minutes: int = 180
    sched_sender_seconds: int = 60

    # Backoff automático (protege o produto e evita banimentos)
    source_backoff_max_minutes: int = 720
    source_backoff_jitter_seconds: int = 20


settings = Settings()
