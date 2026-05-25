from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKUP_SCRIPT = ROOT / "scripts" / "backup_db.sh"
CHECK_SCRIPT = ROOT / "scripts" / "check_latest_backup.sh"
CRONTAB = ROOT / "config" / "raspberry-pi" / "crontab"


def test_backup_script_exists_and_is_executable():
    assert BACKUP_SCRIPT.exists()
    assert os.access(BACKUP_SCRIPT, os.X_OK)


def test_crontab_references_existing_backup_script():
    content = CRONTAB.read_text(encoding="utf-8")
    assert "/home/autohunter/autohunter/scripts/backup_db.sh" in content


def test_backup_script_uses_database_url_and_temp_file_pattern():
    content = BACKUP_SCRIPT.read_text(encoding="utf-8")
    assert "DATABASE_URL" in content
    assert "TMP_FILE" in content
    assert "mv -f \"$TMP_FILE\" \"$FINAL_FILE\"" in content


def test_backup_script_has_no_hardcoded_password_literal():
    content = BACKUP_SCRIPT.read_text(encoding="utf-8").lower()
    assert "password=" not in content


def test_backup_script_loads_env_sources_and_validates_after_loading():
    content = BACKUP_SCRIPT.read_text(encoding="utf-8")
    assert "AUTOHUNTER_ENV_FILE" in content
    assert '/etc/default/autohunter' in content
    assert '/home/autohunter/autohunter/.env' in content
    assert 'load_env_if_exists "./.env"' in content
    assert content.find('load_env_if_exists') < content.find('DATABASE_URL is not set after loading env files')


def test_backup_script_does_not_echo_database_url():
    content = BACKUP_SCRIPT.read_text(encoding="utf-8")
    assert 'echo "$DATABASE_URL"' not in content
    assert 'printenv DATABASE_URL' not in content


def test_check_latest_backup_exit_1_when_no_backup(tmp_path):
    env = os.environ.copy()
    env["AUTOHUNTER_BACKUP_DIR"] = str(tmp_path)
    env["AUTOHUNTER_BACKUP_MAX_AGE_HOURS"] = "30"

    proc = subprocess.run(["bash", str(CHECK_SCRIPT)], env=env, capture_output=True, text=True, check=False)
    assert proc.returncode == 1
    assert "no backup files" in proc.stdout.lower()


def test_check_latest_backup_exit_0_when_recent_backup(tmp_path):
    backup = tmp_path / "autohunter_20260525_020000.sql.gz"
    backup.write_bytes(b"dummy")

    env = os.environ.copy()
    env["AUTOHUNTER_BACKUP_DIR"] = str(tmp_path)
    env["AUTOHUNTER_BACKUP_MAX_AGE_HOURS"] = "30"

    proc = subprocess.run(["bash", str(CHECK_SCRIPT)], env=env, capture_output=True, text=True, check=False)
    assert proc.returncode == 0
    assert "ok: latest backup is recent" in proc.stdout.lower()


def test_check_latest_backup_exit_2_when_stale_backup(tmp_path):
    backup = tmp_path / "autohunter_20200101_000000.sql.gz"
    backup.write_bytes(b"dummy")
    old_epoch = 1_577_836_800  # 2020-01-01T00:00:00Z
    os.utime(backup, (old_epoch, old_epoch))

    env = os.environ.copy()
    env["AUTOHUNTER_BACKUP_DIR"] = str(tmp_path)
    env["AUTOHUNTER_BACKUP_MAX_AGE_HOURS"] = "1"

    proc = subprocess.run(["bash", str(CHECK_SCRIPT)], env=env, capture_output=True, text=True, check=False)
    assert proc.returncode == 2
    assert "stale" in proc.stdout.lower()
