from __future__ import annotations

from app.db import session as session_mod


def test_engine_kwargs_for_postgres_include_pool_and_connect_timeout(monkeypatch):
    monkeypatch.setattr(session_mod.settings, "database_url", "postgresql+psycopg2://u:p@localhost/db")
    monkeypatch.setattr(session_mod.settings, "db_pool_size", 5)
    monkeypatch.setattr(session_mod.settings, "db_max_overflow", 5)
    monkeypatch.setattr(session_mod.settings, "db_pool_recycle", 1800)
    monkeypatch.setattr(session_mod.settings, "db_pool_timeout", 20)
    monkeypatch.setattr(session_mod.settings, "db_connect_timeout", 10)

    kwargs = session_mod._engine_kwargs()

    assert kwargs["pool_pre_ping"] is True
    assert kwargs["pool_size"] == 5
    assert kwargs["max_overflow"] == 5
    assert kwargs["pool_recycle"] == 1800
    assert kwargs["pool_timeout"] == 20
    assert kwargs["connect_args"] == {"connect_timeout": 10}


def test_engine_kwargs_for_sqlite_skip_incompatible_pool_knobs(monkeypatch):
    monkeypatch.setattr(session_mod.settings, "database_url", "sqlite:///./test.db")

    kwargs = session_mod._engine_kwargs()

    assert kwargs == {"pool_pre_ping": True}
