from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.settings import Settings


REPO_ROOT = Path(__file__).resolve().parents[1]
TARGET_DIRS = ("app", "config", "scripts")
ALLOWED_FILE = "app/core/settings.py"


def _iter_python_files() -> list[Path]:
    files: list[Path] = []
    for target in TARGET_DIRS:
        root = REPO_ROOT / target
        if not root.exists():
            continue
        files.extend(sorted(root.rglob("*.py")))
    return files


def _reads_env_directly(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "os" and node.func.attr == "getenv":
                return True
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id == "os" and node.attr == "environ":
                return True
    return False


def test_only_settings_module_reads_environment_directly() -> None:
    offenders: list[str] = []
    for py_file in _iter_python_files():
        rel = py_file.relative_to(REPO_ROOT).as_posix()
        if rel == ALLOWED_FILE:
            continue
        if _reads_env_directly(py_file):
            offenders.append(rel)
    assert not offenders, f"Direct env reads found outside {ALLOWED_FILE}: {offenders}"


def test_settings_parsing_and_defaults() -> None:
    cfg = Settings(
        _env_file=None,
        database_url="sqlite:///tmp.db",
        playwright_service_port="9000",
        enable_playwright="false",
        log_stdout="true",
        use_new_scraper_sources="olx, webmotors",
    )

    assert cfg.database_url == "sqlite:///tmp.db"
    assert cfg.playwright_service_port == 9000
    assert cfg.enable_playwright is False
    assert cfg.log_stdout is True
    assert cfg.should_use_new_scraper_for("olx") is True
    assert cfg.should_use_new_scraper_for("mercadolivre") is False


def test_settings_requires_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
