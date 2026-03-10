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
    public_base_url: str | None = None

    autohunter_admin_user_ids: str | None = None
    autohunter_admin_chat_ids: str | None = None

    admin_deploy_pending_ttl_seconds: int = 120
    admin_deploy_rate_limit_seconds: int = 300
    admin_deploy_wrapper_timeout_seconds: int = 180
    admin_deploy_output_max_chars: int = 1200
    admin_deploy_wrapper_path: str = "/usr/local/bin/autohunter-admin-deploy"
    admin_deploy_app_home: str = "/home/autohunter"
    admin_deploy_use_sudo: bool = True

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

    # Runtime filesystem paths (must stay outside git repo in production)
    runtime_state_dir: str = '/var/lib/autohunter'
    runtime_cache_dir: str = '/var/cache/autohunter'
    runtime_log_dir: str = '/var/log/autohunter'

    health_state_dir: str = '/var/lib/autohunter/health'
    source_audit_root: str = '/var/cache/autohunter/artifacts/source_audit_candidates'
    playwright_browsers_dir: str = '/var/cache/autohunter/pw-browsers'

    # Cookie/session stickiness (Playwright)
    playwright_storage_dir: str = '/var/lib/autohunter/playwright'

    # Playwright queue & dedupe (scaling)
    # - queue_max_jobs: hard cap to avoid RAM blowups on Raspberry Pi
    # - dedupe_inflight: if the same (url, source, proxy) is requested while in-flight, join instead of enqueue
    # - cache_ttl_seconds: short TTL to collapse bursts (manual search / multiple users) without serving stale results for long
    # - cache_max_entries: keep small; browser HTML can be heavy
    playwright_queue_max_jobs: int = 25
    playwright_dedupe_inflight: bool = True
    playwright_cache_ttl_seconds: int = 30
    playwright_cache_max_entries: int = 16

    # Restrict Playwright usage to a subset of sources (comma-separated).
    # Runtime is DB-driven (source_configs.force_browser / browser_fallback_enabled).
    # This setting is an optional safety gate:
    # - empty: no restriction (DB decides when to use browser)
    # - '*': allow any source
    # - 'none'/'off': disable browser for all sources
    # - 'olx,mercadolivre': allow only specific sources
    playwright_sources: str = ""

    # Playwright memory guardrails
    # - context TTL: close idle contexts to free RAM
    # - max contexts: hard cap to avoid RAM blowups on small machines
    playwright_context_ttl_seconds: int = 900  # 15 minutes
    playwright_max_contexts: int = 2

    # Warm up the Playwright worker thread at scheduler start (cheap; does not launch Chromium yet).
    playwright_warmup_on_start: bool = True

    # Smoke test no boot (scheduler/bot)
    playwright_smoke_on_boot: bool = True

    # Facebook Marketplace auth/session
    fb_profile_base_dir: str = '/var/lib/autohunter/profiles/fb'
    fb_debug_base_dir: str = '/var/cache/autohunter/debug/fb'
    fb_max_parallel_browsers: int = 1
    fb_healthcheck_hours: int = 6

    # Bug retry (sem backoff exponencial)
    source_bug_retry_minutes: int = 2

    # Alarmes de erro de programação (somente admins)
    admin_programming_errors_enabled: bool = True
    admin_programming_errors_throttle_seconds: int = 600  # 10 min

    default_alert_limit: int = 30

    # Scheduler tuning (DEV)
    sched_sender_seconds: int = 60
    notification_sender_batch_size: int = 20
    notification_processing_ttl_seconds: int = 300
    notification_retry_base_seconds: int = 30
    notification_max_attempts: int = 3

    # Run a lightweight sender loop inside the Telegram bot process.
    # Useful for DEV/Windows runs where APScheduler (run_scheduler) isn't running.
    enable_sender_in_bot: bool = True
    # APScheduler thread pool. For Raspberry Pi 3, 2 is usually safer (override via env).
    scheduler_workers: int = 2

    # HTTP queue workers (scheduler)
    scheduler_http_workers: int = 3
    scheduler_http_worker_seconds: int = 2
    scheduler_http_worker_count: int = 2

    # HTTP queue cap (protects DB/RAM)
    http_queue_max_jobs: int = 200

    # Consider queue jobs stuck in "running" after this timeout and requeue them.
    scrape_job_running_ttl_seconds: int = 900

    # Max parallel *scraping* jobs running at once (sender/heartbeat are not gated).
    # 1 is the safest default for Raspberry Pi 3.
    scheduler_max_parallel_sources: int = 1

    # Scheduler tick frequency for source jobs. Sources are DB-driven (source_configs.sched_minutes).
    # Keep this small (<=60s) to react quickly, but not too small to avoid DB churn.
    scheduler_tick_seconds: int = 60

    # Backoff automatico (protects product and helps avoid bans)
    source_backoff_max_minutes: int = 720
    source_backoff_jitter_seconds: int = 20


    # Autopilot (observabilidade + detecção de regressões)
    autopilot_enabled: bool = True
    # janela de análise (minutos) para detectar spikes
    autopilot_window_minutes: int = 30
    autopilot_scan_seconds: int = 60
    # mínimo de ocorrências do mesmo fingerprint para abrir finding
    autopilot_min_hits: int = 3
    # throttle por finding (segundos) para alertas no Telegram
    autopilot_alert_throttle_seconds: int = 1800  # 30 min
    # digest diário para admins (UTC hour, ex: 12 = 09:00 America/Sao_Paulo)
    autopilot_daily_digest_enabled: bool = True
    autopilot_daily_digest_hour_utc: int = 12
    telegram_text_max: int = 4000
    safe_chunk: int = 3800

settings = Settings()
