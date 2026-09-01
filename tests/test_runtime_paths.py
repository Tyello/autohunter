from __future__ import annotations

from pathlib import Path

from app.core import runtime_paths
from app.core.settings import settings


def test_state_dir_resolves_and_expands(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "runtime_state_dir", str(tmp_path / "state"))
    result = runtime_paths.state_dir()
    assert result == (tmp_path / "state").resolve()


def test_cache_dir_uses_settings_value(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "runtime_cache_dir", str(tmp_path / "cache"))
    assert runtime_paths.cache_dir() == (tmp_path / "cache").resolve()


def test_log_dir_uses_settings_value(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "runtime_log_dir", str(tmp_path / "logs"))
    assert runtime_paths.log_dir() == (tmp_path / "logs").resolve()


def test_playwright_storage_dir_uses_settings_value(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "playwright_storage_dir", str(tmp_path / "pw"))
    assert runtime_paths.playwright_storage_dir() == (tmp_path / "pw").resolve()


def test_health_dir_uses_settings_value(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "health_state_dir", str(tmp_path / "health"))
    assert runtime_paths.health_dir() == (tmp_path / "health").resolve()


def test_source_audit_dir_uses_settings_value(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "source_audit_root", str(tmp_path / "audit"))
    assert runtime_paths.source_audit_dir() == (tmp_path / "audit").resolve()


def test_playwright_browsers_dir_uses_settings_value(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "playwright_browsers_dir", str(tmp_path / "browsers"))
    assert runtime_paths.playwright_browsers_dir() == (tmp_path / "browsers").resolve()


def test_does_not_create_directory_itself(monkeypatch, tmp_path):
    target = tmp_path / "not_created_yet"
    monkeypatch.setattr(settings, "runtime_state_dir", str(target))
    runtime_paths.state_dir()
    assert not target.exists()
