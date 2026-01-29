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

    # Chat IDs que devem receber alertas automáticos (erros/backoff/monitoramento).
    # Separe por vírgula. Se vazio, usa autohunter_admins (compatibilidade).
    autohunter_admin_alert_chats: str | None = None

    default_user_timezone: str = 'America/Sao_Paulo'

    # Feature flags
    enable_scheduler_in_api: bool = False

    # OLX
    enable_olx_browser_fallback: bool = True
    # Force OLX scraping via Playwright (recommended when OLX returns 403/Cloudflare to HTTP clients)
    olx_force_browser: bool = False

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
    sched_sender_seconds: int = 60
    # APScheduler thread pool. For Raspberry Pi 3, 2 is usually safer (override via env).
    scheduler_workers: int = 2

    # Max parallel *scraping* jobs running at once (sender/heartbeat are not gated).
    # 1 is the safest default for Raspberry Pi 3.
    scheduler_max_parallel_sources: int = 1

    # Backoff automatico (protects product and helps avoid bans)
    source_backoff_max_minutes: int = 720
    source_backoff_jitter_seconds: int = 20

    telegram_text_max: int = 4000
    safe_chunk: int = 3800

settings = Settings()