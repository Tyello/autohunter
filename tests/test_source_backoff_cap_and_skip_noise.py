from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.models.source_run import SourceRun
from app.models.source_state import SourceState
from app.services import source_execution_service as ses
from app.services.source_backoff_service import _compute_backoff_minutes
from app.services.source_execution_service import (
    _base_cooldown_minutes_for,
    _max_backoff_minutes_for,
    run_source_for_all_wishlists,
)


def test_mercadolivre_backoff_is_capped_at_24h():
    """Bloqueio do ML e reputacao de IP, mas 7 dias parados (prod 28/10-08/11) e excessivo:
    teto de 24h, mesmo teto do OLX."""
    cfg = SimpleNamespace(cooldown_minutes=0)
    base = _base_cooldown_minutes_for("mercadolivre", cfg)
    cap = _max_backoff_minutes_for("mercadolivre")
    assert base == 240
    assert cap == 1440
    assert [_compute_backoff_minutes(base, n, cap) for n in (1, 2, 3, 4, 5, 6)] == [240, 480, 960, 1440, 1440, 1440]


@pytest.fixture
def log_calls(monkeypatch):
    """system_logs.tags e ARRAY (Postgres) e nao roda em SQLite: contamos as escritas em vez de executa-las."""
    calls = {"log": 0, "event": 0}
    monkeypatch.setattr(ses, "log", lambda *a, **k: calls.__setitem__("log", calls["log"] + 1))
    monkeypatch.setattr(ses, "emit_event", lambda *a, **k: calls.__setitem__("event", calls["event"] + 1))
    return calls


def _skipped_runs(db, source: str):
    return db.query(SourceRun).filter(SourceRun.source == source, SourceRun.status == "skipped").all()


def test_repeated_backoff_skips_are_recorded_once_per_window(db, log_calls):
    """Prod: ~960 skips/dia por source em backoff, cada um com 3 escritas. Um registro por janela basta."""
    until = datetime.now(timezone.utc) + timedelta(hours=2)
    db.add(SourceState(source="olx", next_allowed_at=until, last_status="blocked", consecutive_blocks=2))
    db.commit()

    results = [run_source_for_all_wishlists(db, "olx", kind="scheduler") for _ in range(3)]

    assert all(r["status"] == "skipped" and r["reason"] == "backoff" for r in results)
    assert len(_skipped_runs(db, "olx")) == 1
    assert log_calls == {"log": 1, "event": 1}
    st = db.query(SourceState).filter(SourceState.source == "olx").one()
    assert st.last_status == "skipped:backoff"


def test_new_backoff_window_is_recorded_again(db, log_calls):
    first = datetime.now(timezone.utc) + timedelta(hours=2)
    db.add(SourceState(source="olx", next_allowed_at=first, last_status="blocked"))
    db.commit()
    run_source_for_all_wishlists(db, "olx", kind="scheduler")
    run_source_for_all_wishlists(db, "olx", kind="scheduler")
    assert len(_skipped_runs(db, "olx")) == 1

    st = db.query(SourceState).filter(SourceState.source == "olx").one()
    st.next_allowed_at = first + timedelta(hours=4)  # novo bloqueio estendeu a janela
    db.commit()
    run_source_for_all_wishlists(db, "olx", kind="scheduler")

    assert len(_skipped_runs(db, "olx")) == 2
    assert log_calls == {"log": 2, "event": 2}
