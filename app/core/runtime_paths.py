from __future__ import annotations

from pathlib import Path

from app.core.settings import settings


def _norm(path: str) -> Path:
    return Path(path).expanduser().resolve()


def _ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def state_dir() -> Path:
    return _norm(settings.runtime_state_dir)


def cache_dir() -> Path:
    return _norm(settings.runtime_cache_dir)


def log_dir() -> Path:
    return _norm(settings.runtime_log_dir)


def playwright_storage_dir() -> Path:
    return _norm(settings.playwright_storage_dir)


def health_dir() -> Path:
    return _norm(settings.health_state_dir)


def source_audit_dir() -> Path:
    return _norm(settings.source_audit_root)


def playwright_browsers_dir() -> Path:
    return _norm(settings.playwright_browsers_dir)


def ensure_runtime_dirs() -> None:
    for fn in (
        state_dir,
        cache_dir,
        log_dir,
        playwright_storage_dir,
        health_dir,
        source_audit_dir,
        playwright_browsers_dir,
    ):
        _ensure(fn())
