from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.source_staleness_service import (
    evaluate_source_staleness,
    heartbeat_is_stale,
    stale_threshold_minutes,
)


def test_evaluate_staleness_no_last_run_is_stale():
    now = datetime.now(timezone.utc)
    result = evaluate_source_staleness(now=now, last_run_at=None, sched_minutes=60)
    assert result.stale is True
    assert result.age_minutes is None
    assert result.overdue_minutes is None


def test_evaluate_staleness_handles_naive_datetimes():
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    last_run = (datetime.now(timezone.utc) - timedelta(minutes=5)).replace(tzinfo=None)
    result = evaluate_source_staleness(now=now, last_run_at=last_run, sched_minutes=60)
    assert result.stale is False


def test_heartbeat_is_stale_when_missing():
    assert heartbeat_is_stale(datetime.now(timezone.utc), None) is True


# --- Fronteiras, padroes e entradas invalidas (guiado por teste de mutacao) -----------------
import dataclasses

import pytest

from app.services.source_staleness_service import SourceStaleness

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def _stale(age_min: int, **kw):
    return evaluate_source_staleness(now=NOW, last_run_at=NOW - timedelta(minutes=age_min), **kw)


def test_threshold_defaults_are_factor_2_min_180_and_sched_60():
    assert stale_threshold_minutes(100, min_global_minutes=0) == 200  # factor padrao 2.0
    assert stale_threshold_minutes(1) == 180  # piso padrao 180
    assert stale_threshold_minutes(None, min_global_minutes=0) == 120  # sched padrao 60 x 2.0


def test_threshold_factor_is_rounded_and_min_wins_only_when_larger():
    assert stale_threshold_minutes(100, factor=1.5, min_global_minutes=0) == 150
    assert stale_threshold_minutes(100, factor=2.0, min_global_minutes=250) == 250
    assert stale_threshold_minutes(100, factor=2.0, min_global_minutes=200) == 200


@pytest.mark.parametrize("bad", [0, -5, None, "abc", "", object()])
def test_threshold_invalid_sched_falls_back_to_default(bad):
    assert stale_threshold_minutes(bad, default_sched_minutes=70, factor=1.0, min_global_minutes=0) == 70


def test_threshold_options_are_keyword_only():
    with pytest.raises(TypeError):
        stale_threshold_minutes(60, 2.0)  # type: ignore[misc]


@pytest.mark.parametrize(
    "age, stale, overdue",
    [(179, False, 0), (180, False, 0), (181, True, 1), (300, True, 120)],
)
def test_staleness_boundary_is_strictly_greater_than_threshold(age, stale, overdue):
    r = _stale(age, sched_minutes=60)  # limite = max(180, 60 x 2) = 180
    assert (r.stale, r.overdue_minutes, r.threshold_minutes, r.age_minutes) == (stale, overdue, 180, age)


def test_staleness_defaults_factor_sched_and_floor():
    assert _stale(401, sched_minutes=200).stale is True  # factor padrao 2.0 -> limite 400
    assert _stale(400, sched_minutes=200).stale is False
    assert _stale(121, sched_minutes=None, min_global_minutes=0).stale is True  # sched padrao 60 -> 120
    assert _stale(120, sched_minutes=None, min_global_minutes=0).stale is False


def test_staleness_age_counts_whole_minutes_and_never_negative():
    r = evaluate_source_staleness(now=NOW, last_run_at=NOW - timedelta(seconds=119), sched_minutes=60)
    assert r.age_minutes == 1  # 119s -> 1 min (nao arredonda para cima)
    future = evaluate_source_staleness(now=NOW, last_run_at=NOW + timedelta(minutes=10), sched_minutes=60)
    assert future.age_minutes == 0 and future.stale is False


def test_staleness_result_is_immutable():
    r = _stale(5, sched_minutes=60)
    assert isinstance(r, SourceStaleness)
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.stale = True  # type: ignore[misc]


@pytest.mark.parametrize(
    "age, expected",
    [(14, False), (15, False), (16, True)],
)
def test_heartbeat_boundary_default_15_minutes_is_strict(age, expected):
    assert heartbeat_is_stale(NOW, NOW - timedelta(minutes=age)) is expected


def test_heartbeat_zero_or_none_cutoff_falls_back_to_15_but_explicit_value_is_kept():
    last = NOW - timedelta(minutes=20)
    assert heartbeat_is_stale(NOW, last, stale_after_minutes=0) is True  # 0 -> 15
    assert heartbeat_is_stale(NOW, last, stale_after_minutes=30) is False  # 30 respeitado (nao vira 15)
    assert heartbeat_is_stale(NOW, NOW - timedelta(minutes=10), stale_after_minutes=0) is False


def test_heartbeat_mixes_naive_and_aware_datetimes_as_utc():
    naive_now = NOW.replace(tzinfo=None)
    recent_aware = NOW - timedelta(minutes=5)
    old_naive = (NOW - timedelta(minutes=30)).replace(tzinfo=None)
    assert heartbeat_is_stale(naive_now, recent_aware) is False
    assert heartbeat_is_stale(NOW, old_naive) is True
    assert heartbeat_is_stale(naive_now, old_naive) is True


def test_heartbeat_respects_non_utc_offsets_without_replacing_them():
    br = timezone(timedelta(hours=-3))
    now_br = datetime(2026, 1, 1, 9, 0, tzinfo=br)  # = 12:00Z
    assert heartbeat_is_stale(now_br, datetime(2026, 1, 1, 11, 30, tzinfo=timezone.utc)) is True  # 30 min atras
    assert heartbeat_is_stale(now_br, datetime(2026, 1, 1, 11, 55, tzinfo=timezone.utc)) is False  # 5 min atras


def test_threshold_sched_of_one_minute_is_valid_not_replaced_by_default():
    # fronteira de `v > 0`: 1 e valido; so 0/negativo/invalido caem no padrao
    assert stale_threshold_minutes(1, factor=1.0, min_global_minutes=0, default_sched_minutes=60) == 1


@pytest.mark.parametrize("cutoff", [0, None])
@pytest.mark.parametrize("age, expected", [(14, False), (15, False), (16, True)])
def test_heartbeat_fallback_cutoff_is_exactly_15_minutes(cutoff, age, expected):
    assert heartbeat_is_stale(NOW, NOW - timedelta(minutes=age), stale_after_minutes=cutoff) is expected
