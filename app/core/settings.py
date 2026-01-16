from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",   # pode manter assim
    )

    database_url: str
    telegram_bot_token: str | None = None
    autohunter_admins: str | None = None

    # Feature flags
    enable_scheduler_in_api: bool = False
    enable_olx: bool = False
    olx_cooldown_minutes: int = 60

    default_alert_limit: int = 30

    # Scheduler tuning (DEV)
    sched_ml_minutes: int = 30
    sched_olx_minutes: int = 30
    sched_sender_seconds: int = 60

settings = Settings()