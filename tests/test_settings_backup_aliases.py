from __future__ import annotations

from app.core.settings import Settings


def test_settings_accepts_autohunter_backup_dir_alias():
    out = Settings.model_validate(
        {
            "database_url": "sqlite:///tmp.db",
            "AUTOHUNTER_BACKUP_DIR": "/tmp/autohunter-backups",
        }
    )
    assert out.backup_dir == "/tmp/autohunter-backups"


def test_settings_accepts_autohunter_backup_max_age_alias():
    out = Settings.model_validate(
        {
            "database_url": "sqlite:///tmp.db",
            "AUTOHUNTER_BACKUP_MAX_AGE_HOURS": "42",
        }
    )
    assert out.backup_max_age_hours == 42


def test_settings_accepts_autohunter_backup_quality_aliases():
    out = Settings.model_validate(
        {
            "database_url": "sqlite:///tmp.db",
            "AUTOHUNTER_BACKUP_MIN_SIZE_BYTES": "200000",
            "AUTOHUNTER_BACKUP_VALIDATE_CRITICAL_TABLES": "true",
            "AUTOHUNTER_BACKUP_MIN_USERS": "1",
            "AUTOHUNTER_BACKUP_MIN_WISHLISTS": "1",
            "AUTOHUNTER_BACKUP_MIN_SOURCE_CONFIGS": "1",
        }
    )
    assert out.backup_min_size_bytes == 200000
    assert out.backup_validate_critical_tables is True
    assert out.backup_min_users == 1
    assert out.backup_min_wishlists == 1
    assert out.backup_min_source_configs == 1
