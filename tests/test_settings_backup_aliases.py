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
