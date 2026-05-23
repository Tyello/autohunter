from pathlib import Path


def test_raspberry_crontab_does_not_reference_legacy_scripts():
    content = Path("config/raspberry-pi/crontab").read_text(encoding="utf-8")
    assert "cache_manager" not in content
    assert "database_optimizer" not in content
    assert "cleanup_operational_data.py --apply" in content
