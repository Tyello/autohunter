import pytest

from scripts.cleanup_operational_data import run_cleanup


def test_cleanup_sqlite_apply_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import settings as settings_mod

    monkeypatch.setattr(settings_mod.settings, "database_url", "sqlite:///tmp.db")
    with pytest.raises(RuntimeError):
        run_cleanup(apply=True)
