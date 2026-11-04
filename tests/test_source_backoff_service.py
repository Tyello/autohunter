from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.source_state import SourceState
from app.services.source_backoff_service import (
    is_source_allowed,
    mark_blocked,
    mark_bug,
    mark_error,
    mark_skipped,
    mark_success,
)


def test_is_source_allowed_creates_state_when_missing(db):
    availability = is_source_allowed(db, "olx")
    assert availability.is_allowed is True
    assert db.query(SourceState).filter(SourceState.source == "olx").one()


def test_mark_success_clears_backoff_and_counters(db):
    mark_error(db, "olx", base_cooldown_minutes=5, error="boom")
    db.commit()

    mark_success(db, "olx")
    db.commit()

    st = db.query(SourceState).filter(SourceState.source == "olx").one()
    assert st.consecutive_failures == 0
    assert st.consecutive_blocks == 0
    assert st.next_allowed_at is None
    assert st.last_status == "success"


def test_mark_skipped_records_reason(db):
    mark_skipped(db, "olx", "already_recent")
    db.commit()

    st = db.query(SourceState).filter(SourceState.source == "olx").one()
    assert st.last_status == "skipped:already_recent"


def test_mark_blocked_sets_backoff_and_is_not_allowed_after(db):
    minutes = mark_blocked(db, "olx", base_cooldown_minutes=10, http_status=403, url="https://x")
    db.commit()
    db.expire_all()

    assert minutes >= 10
    st = db.query(SourceState).filter(SourceState.source == "olx").one()
    st.next_allowed_at = st.next_allowed_at.replace(tzinfo=timezone.utc)
    availability = is_source_allowed(db, "olx")
    assert availability.is_allowed is False
    assert availability.reason == "backoff"


def test_mark_blocked_escalates_exponentially_with_consecutive_blocks(db):
    m1 = mark_blocked(db, "olx", base_cooldown_minutes=10)
    db.commit()
    m2 = mark_blocked(db, "olx", base_cooldown_minutes=10)
    db.commit()
    m3 = mark_blocked(db, "olx", base_cooldown_minutes=10)
    db.commit()

    assert m1 == 10
    assert m2 == 20
    assert m3 == 40


def test_mark_blocked_respects_max_backoff_minutes(db):
    for _ in range(6):
        minutes = mark_blocked(db, "olx", base_cooldown_minutes=10, max_backoff_minutes=30)
        db.commit()
    assert minutes == 30


def test_mark_error_escalates_and_resets_blocks(db):
    mark_blocked(db, "olx", base_cooldown_minutes=10)
    db.commit()

    mark_error(db, "olx", base_cooldown_minutes=5, error="timeout")
    db.commit()

    st = db.query(SourceState).filter(SourceState.source == "olx").one()
    assert st.consecutive_blocks == 0
    assert st.consecutive_failures == 1
    assert st.last_status == "error"


def test_mark_blocked_grace_tolerates_first_block_then_escalates(db):
    kw = dict(base_cooldown_minutes=120, max_backoff_minutes=1440, grace_blocks=1, grace_minutes=5)
    assert mark_blocked(db, "olx", **kw) == 5       # bloqueio isolado: backoff curto
    assert mark_blocked(db, "olx", **kw) == 120     # 2o seguido: backoff longo comeca na base
    assert mark_blocked(db, "olx", **kw) == 240
    mark_success(db, "olx")
    assert mark_blocked(db, "olx", **kw) == 5       # sucesso zera a tolerancia


def test_mark_blocked_without_grace_is_unchanged(db):
    assert mark_blocked(db, "olx", base_cooldown_minutes=120) == 120
    assert mark_blocked(db, "olx", base_cooldown_minutes=120) == 240


# --- Fronteiras, padroes e arredondamentos (guiado por teste de mutacao) ---------------------
from datetime import datetime, timedelta, timezone

import pytest

from app.core.settings import settings
from app.services import source_backoff_service as sbs

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def clock(monkeypatch):
    monkeypatch.setattr(sbs, "_utcnow", lambda: T0)
    monkeypatch.setattr(settings, "source_backoff_jitter_seconds", 20)
    monkeypatch.setattr(settings, "source_backoff_max_minutes", 720)
    return T0


def _state(db, source="olx"):
    db.flush()
    st = db.query(SourceState).filter(SourceState.source == source).one()
    # SQLite devolve datetime sem fuso (UTC); normaliza para comparar com o relogio fixo.
    for col in ("next_allowed_at", "last_run_at", "last_effective_run_at"):
        v = getattr(st, col)
        if v is not None and v.tzinfo is None:
            setattr(st, col, v.replace(tzinfo=timezone.utc))
    return st


@pytest.mark.parametrize(
    "base, exponent, cap, expected",
    [
        (0, 1, None, 1),  # base 0/None vira 1 minuto
        (None, 3, None, 4),
        (5, 0, None, 5),  # expoente <= 0 nao divide: 2**0
        (5, -3, None, 5),
        (5, 1, None, 5),
        (5, 2, None, 10),
        (5, 4, None, 40),
        (5, 10, None, 720),  # teto global padrao (settings)
        (5, 10, 100, 100),  # teto explicito vence o global
        (5, 2, 7, 7),
    ],
)
def test_compute_backoff_minutes_table(clock, base, exponent, cap, expected):
    assert sbs._compute_backoff_minutes(base, exponent, cap) == expected


def test_compute_backoff_uses_settings_cap_and_falls_back_to_720_when_unset(clock, monkeypatch):
    monkeypatch.setattr(settings, "source_backoff_max_minutes", 100)
    assert sbs._compute_backoff_minutes(60, 5) == 100
    monkeypatch.setattr(settings, "source_backoff_max_minutes", 0)
    assert sbs._compute_backoff_minutes(60, 5) == 720  # 0/None -> 720


def test_source_state_is_per_source_and_reused(db, clock):
    a = sbs._get_or_create_state(db, "a")
    b = sbs._get_or_create_state(db, "b")
    assert a is not b and a.source == "a" and b.source == "b"
    assert sbs._get_or_create_state(db, "a") is a  # reaproveita, nao duplica
    assert sbs._get_or_create_state(db, "b") is b
    assert db.query(SourceState).count() == 2


def test_is_source_allowed_boundary_is_strictly_in_the_future(db, clock):
    st = sbs._get_or_create_state(db, "olx")
    st.next_allowed_at = T0 + timedelta(seconds=1)
    a = sbs.is_source_allowed(db, "olx")
    assert a.is_allowed is False and a.reason == "backoff" and a.next_allowed_at == T0 + timedelta(seconds=1)
    st.next_allowed_at = T0  # exatamente agora: liberado
    assert sbs.is_source_allowed(db, "olx").is_allowed is True
    st.next_allowed_at = T0 - timedelta(seconds=1)
    assert sbs.is_source_allowed(db, "olx").is_allowed is True
    st.next_allowed_at = None
    assert sbs.is_source_allowed(db, "olx").is_allowed is True


def test_mark_success_rate_limit_sets_exact_next_allowed(db, clock):
    sbs.mark_success(db, "olx", rate_limit_seconds=30, payload={"k": 1})
    st = _state(db)
    assert st.next_allowed_at == T0 + timedelta(seconds=30)
    assert st.last_run_at == T0 and st.last_effective_run_at == T0
    assert st.last_status == "success" and st.last_payload == {"k": 1} and st.last_error is None


@pytest.mark.parametrize("rl", [0, -10, None])
def test_mark_success_without_positive_rate_limit_clears_next_allowed(db, clock, rl):
    sbs._get_or_create_state(db, "olx").next_allowed_at = T0 + timedelta(hours=1)
    sbs.mark_success(db, "olx", rate_limit_seconds=rl)
    assert _state(db).next_allowed_at is None


def test_mark_success_options_are_keyword_only(db, clock):
    with pytest.raises(TypeError):
        sbs.mark_success(db, "olx", 30)  # type: ignore[misc]


def test_mark_blocked_grace_sequence_and_exact_times(db, clock):
    mins = [
        sbs.mark_blocked(db, "olx", base_cooldown_minutes=10, grace_blocks=2, grace_minutes=7)
        for _ in range(5)
    ]
    assert mins == [7, 7, 10, 20, 40]  # 2 de tolerancia, depois base x 2^(n-grace-1)
    st = _state(db)
    assert st.consecutive_blocks == 5
    assert st.next_allowed_at == T0 + timedelta(minutes=40, seconds=20)  # + jitter padrao


def test_mark_blocked_default_grace_minutes_is_five_and_min_is_one(db, clock):
    assert sbs.mark_blocked(db, "a", base_cooldown_minutes=10, grace_blocks=1) == 5  # grace_minutes padrao
    assert sbs.mark_blocked(db, "b", base_cooldown_minutes=10, grace_blocks=1, grace_minutes=0) == 1
    assert sbs.mark_blocked(db, "c", base_cooldown_minutes=10, grace_blocks=None) == 10  # None -> sem grace


def test_mark_blocked_records_payload_and_resets_failures(db, clock):
    st = sbs._get_or_create_state(db, "olx")
    st.consecutive_failures = 4
    m = sbs.mark_blocked(db, "olx", base_cooldown_minutes=3, http_status=403, url="https://x/y")
    st = _state(db)
    assert st.consecutive_failures == 0 and st.last_status == "blocked" and st.last_error is None
    assert st.last_payload == {"http_status": 403, "url": "https://x/y", "backoff_minutes": m}
    assert st.last_run_at == T0 and st.last_effective_run_at == T0


@pytest.mark.parametrize(
    "setting, expected_jitter",
    [(45, 45), (1, 1), (0, 20), (None, 20)],  # 0/None caem no padrao de 20s
)
def test_jitter_setting_is_added_and_falls_back_to_20(db, clock, monkeypatch, setting, expected_jitter):
    monkeypatch.setattr(settings, "source_backoff_jitter_seconds", setting)
    sbs.mark_blocked(db, "a", base_cooldown_minutes=2)
    sbs.mark_error(db, "b", base_cooldown_minutes=2, error="x")
    assert _state(db, "a").next_allowed_at == T0 + timedelta(minutes=2, seconds=expected_jitter)
    assert _state(db, "b").next_allowed_at == T0 + timedelta(minutes=2, seconds=expected_jitter)


def test_mark_error_counts_failures_from_zero_and_sets_exact_times(db, clock):
    assert sbs.mark_error(db, "olx", base_cooldown_minutes=5, error="e1", url="u") == 5
    st = _state(db)
    assert st.consecutive_failures == 1 and st.consecutive_blocks == 0
    assert st.next_allowed_at == T0 + timedelta(minutes=5, seconds=20)
    assert st.last_status == "error" and st.last_error == "e1"
    assert st.last_payload == {"url": "u", "backoff_minutes": 5}
    assert sbs.mark_error(db, "olx", base_cooldown_minutes=5, error="e2") == 10
    assert _state(db).consecutive_failures == 2


def test_mark_error_message_is_cut_at_800_chars(db, clock):
    sbs.mark_error(db, "olx", base_cooldown_minutes=1, error="x" * 900)
    assert _state(db).last_error == "x" * 800


def test_mark_bug_default_retry_is_two_minutes_and_resets_counters(db, clock, monkeypatch):
    monkeypatch.setattr(settings, "source_bug_retry_minutes", 2)
    st = sbs._get_or_create_state(db, "olx")
    st.consecutive_failures, st.consecutive_blocks = 3, 4
    assert sbs.mark_bug(db, "olx", error="kaboom", url="u") == 2
    st = _state(db)
    assert st.consecutive_failures == 0 and st.consecutive_blocks == 0
    assert st.next_allowed_at == T0 + timedelta(minutes=2, seconds=20)
    assert st.last_status == "error" and st.last_error == "kaboom"
    assert st.last_payload == {"url": "u", "bug": True, "backoff_minutes": 2}


@pytest.mark.parametrize("configured, minutes", [(5, 5), (0, 2), (None, 2)])  # 0/None -> padrao 2
def test_mark_bug_retry_minutes_setting(db, clock, monkeypatch, configured, minutes):
    monkeypatch.setattr(settings, "source_bug_retry_minutes", configured)
    assert sbs.mark_bug(db, "olx", error="e") == minutes
    assert _state(db).next_allowed_at == T0 + timedelta(minutes=minutes, seconds=20)


def test_mark_bug_negative_retry_disables_backoff(db, clock, monkeypatch):
    monkeypatch.setattr(settings, "source_bug_retry_minutes", -1)
    sbs._get_or_create_state(db, "olx").next_allowed_at = T0 + timedelta(hours=1)
    assert sbs.mark_bug(db, "olx", error="e") == -1
    assert _state(db).next_allowed_at is None
    assert sbs.is_source_allowed(db, "olx").is_allowed is True


@pytest.mark.parametrize("error, stored", [(None, "bug"), ("", "bug"), ("y" * 900, "y" * 800)])
def test_mark_bug_error_text(db, clock, error, stored):
    sbs.mark_bug(db, "olx", error=error)
    assert _state(db).last_error == stored
