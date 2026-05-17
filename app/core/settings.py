import os
from pathlib import Path

from pydantic import PrivateAttr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT_DIR / ".env"


class Settings(BaseSettings):
    _per_source_scraper_flags: dict[str, bool] = PrivateAttr(default_factory=dict)
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding='utf-8',
        extra='ignore',
        case_sensitive=False,
    )

    database_url: str
    telegram_bot_token: str | None = None
    telegram_enabled: bool = True
    autohunter_admins: str | None = None
    public_base_url: str | None = None
    mercado_pago_monthly_payment_link: str | None = None
    mercado_pago_annual_payment_link: str | None = None

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
    use_new_scrapers: bool = False
    use_new_scraper_sources: str = ""

    # OLX
    enable_olx_browser_fallback: bool = True
    # Force OLX scraping via Playwright (recommended when OLX returns 403/Cloudflare to HTTP clients)
    olx_force_browser: bool = False

    # Playwright / Browser mode
    enable_playwright: bool = True
    playwright_headless: bool = True
    playwright_service_host: str = "127.0.0.1"
    playwright_service_port: int = 8787

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
    browser_manager_context_ttl_seconds: int = 300
    browser_manager_max_contexts: int = 5

    # Warm up the Playwright worker thread at scheduler start (cheap; does not launch Chromium yet).
    playwright_warmup_on_start: bool = True

    # Smoke test no boot (scheduler/bot)
    playwright_smoke_on_boot: bool = True

    # Facebook Marketplace auth/session
    fb_profile_base_dir: str = '/var/lib/autohunter/profiles/fb'
    fb_debug_base_dir: str = '/var/cache/autohunter/debug/fb'
    fb_max_parallel_browsers: int = 1
    fb_healthcheck_hours: int = 6

    # WebMotors debug artifacts (outside repo/runtime-only)
    webmotors_debug_capture_enabled: bool = False
    webmotors_debug_dir: str = '/var/cache/autohunter/debug/webmotors'
    webmotors_debug_max_artifacts: int = 25
    webmotors_debug_text_snippet_chars: int = 500

    # Bug retry (sem backoff exponencial)
    source_bug_retry_minutes: int = 2

    # Alarmes de erro de programação (somente admins)
    admin_programming_errors_enabled: bool = True
    admin_programming_errors_throttle_seconds: int = 600  # 10 min

    default_alert_limit: int = 30

    # Scheduler tuning (DEV)
    sched_sender_seconds: int = 60
    notification_sender_batch_size: int = 20
    # Transaction flush size for sender status updates.
    # 1 = safest (commit per notification). >1 enables micro-batching.
    notification_sender_commit_batch_size: int = 1
    notification_processing_ttl_seconds: int = 300
    notification_retry_base_seconds: int = 30
    notification_max_attempts: int = 3
    match_candidates_per_run: int = 250
    match_max_queue_per_wishlist: int = 10
    listing_inactive_missing_runs_threshold: int = 3
    tracking_price_alerts_enabled: bool = True
    tracking_price_alerts_interval_minutes: int = 60
    tracking_price_alerts_batch_size: int = 50
    tracking_price_drop_alert_cooldown_hours: int = 24
    tracking_price_drop_alert_min_amount: int = 500
    tracking_price_drop_alert_min_pct: float = 1.0

    # Auction notification pilot job (safe defaults)
    auction_notifications_enabled: bool = False
    auction_notifications_dry_run: bool = True
    auction_notifications_max_wishlists_per_run: int = 20
    auction_notifications_max_per_wishlist: int = 1
    auction_notifications_max_per_user_per_day: int = 3
    auction_notifications_scheduler_minutes: int = 60
    auction_notifications_min_score: int = 60
    auction_notifications_max_lot_age_hours: int = 48
    auction_notifications_kill_switch: bool = False

    # Logging
    log_level: str = "info"
    log_stdout: bool = False

    # Source audit
    source_audit_debug: bool = False
    source_audit_max_bytes: int = 250000

    # OLX
    olx_health_path: str | None = None
    olx_force_browser_hours: int = 6
    olx_impersonate: str = "chrome120"

    # Notifications (legacy module compatibility)
    whatsapp_enabled: bool = False
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_whatsapp_number: str = "whatsapp:+14155238886"
    email_enabled: bool = False
    use_aws_ses: bool = False
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    from_email: str | None = None
    aws_region: str = "us-east-1"
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    ses_from_email: str | None = None
    sms_enabled: bool = False
    twilio_sms_number: str | None = None
    webhook_enabled: bool = False
    webhook_url: str | None = None
    webhook_secret: str | None = None
    webhook_method: str = "POST"
    telegram_rate_limit: int = 20
    whatsapp_rate_limit: int = 10
    email_rate_limit: int = 50
    sms_rate_limit: int = 10
    webhook_rate_limit: int = 100
    notification_queue_max_size: int = 1000
    notification_worker_enabled: bool = True
    notification_max_retries: int = 3
    notification_retry_backoff: float = 2.0

    # Integrations/scripts
    use_redis_cache: bool = False
    redis_url: str | None = None

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

    # Source/scheduler staleness diagnostics
    source_stale_factor: float = 2.0
    source_stale_min_minutes: int = 180
    scheduler_heartbeat_stale_minutes: int = 15
    scheduler_global_stale_min_sources: int = 3
    scheduler_global_stale_ratio: float = 0.6


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
    source_config_cache_ttl_seconds: int = 60
    operational_retention_system_logs_days: int = 7
    operational_retention_telemetry_events_days: int = 7
    operational_retention_scrape_jobs_days: int = 7
    operational_retention_source_runs_days: int = 30
    operational_retention_notifications_days: int = 90
    operational_retention_wishlist_activity_days: int = 90

    # Filesystem cleanup (runtime artifacts/debug only; safe defaults)
    filesystem_cleanup_enabled: bool = True
    filesystem_cleanup_artifacts_days: int = 7
    filesystem_cleanup_debug_days: int = 7
    filesystem_cleanup_max_delete_per_run: int = 1000

    # Disk pressure alerts
    disk_alert_root_used_pct: float = 85.0
    disk_alert_cache_limit_gb: float = 5.0

    def model_post_init(self, __context) -> None:
        self._per_source_scraper_flags: dict[str, bool] = {}
        for key, value in os.environ.items():
            if not key.startswith("USE_NEW_SCRAPER_"):
                continue
            source = key.removeprefix("USE_NEW_SCRAPER_").strip().lower()
            if not source:
                continue
            self._per_source_scraper_flags[source] = str(value).strip().lower() in {"1", "true", "yes", "y", "on"}

    def should_use_new_scraper_for(self, source: str) -> bool | None:
        src = (source or "").strip().lower()
        if not src:
            return None
        if src in self._per_source_scraper_flags:
            return self._per_source_scraper_flags[src]
        if self.use_new_scraper_sources.strip():
            allowed = {item.strip().lower() for item in self.use_new_scraper_sources.split(",") if item.strip()}
            return src in allowed
        return None


    @property
    def auction_notifications_min_score_safe(self) -> int:
        try:
            value = int(self.auction_notifications_min_score)
        except Exception:
            value = 60
        return max(0, min(100, value))

    @property
    def auction_notifications_max_lot_age_hours_safe(self) -> int:
        try:
            value = int(self.auction_notifications_max_lot_age_hours)
        except Exception:
            value = 48
        if value <= 0:
            return 0
        return max(1, min(720, value))

    def ensure_playwright_browsers_env(self) -> None:
        browsers_path = Path(self.playwright_browsers_dir).expanduser().resolve()
        browsers_path.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(browsers_path))

    def merged_subprocess_env(self, *, home: str | None = None, extra: dict[str, str] | None = None) -> dict[str, str]:
        env = os.environ.copy()
        if home:
            env["HOME"] = home
            env["XDG_CONFIG_HOME"] = f"{home}/.config"
        if extra:
            env.update(extra)
        return env

settings = Settings()


def merged_subprocess_env(*, home: str | None = None, extra: dict[str, str] | None = None) -> dict[str, str]:
    return settings.merged_subprocess_env(home=home, extra=extra)


def ensure_playwright_browsers_env() -> None:
    settings.ensure_playwright_browsers_env()
