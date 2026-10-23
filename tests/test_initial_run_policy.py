from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest

from app.core.settings import settings
from app.services import initial_run_policy as irp

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


def test_defaults_come_from_settings_and_ml_is_more_conservative(monkeypatch):
    monkeypatch.setattr(settings, "initial_run_cooldown_minutes", 30)
    monkeypatch.setattr(settings, "initial_run_debounce_min_seconds", 90)
    monkeypatch.setattr(settings, "initial_run_debounce_max_seconds", 120)

    olx = irp.read_initial_run_policy("olx", {})
    ml = irp.read_initial_run_policy("mercadolivre", None)

    assert (olx.cooldown_minutes, olx.debounce_min_seconds, olx.debounce_max_seconds) == (30, 90, 120)
    assert ml.cooldown_minutes == 60


def test_source_config_extra_overrides_cooldown(monkeypatch):
    monkeypatch.setattr(settings, "initial_run_cooldown_minutes", 30)

    pol = irp.read_initial_run_policy("olx", {"initial_run": {"cooldown_minutes": 5}})
    assert pol.cooldown_minutes == 5

    pol = irp.read_initial_run_policy("mercadolivre", {"initial_run": {"cooldown_minutes": 0}})
    assert pol.cooldown_minutes == 0


@pytest.mark.parametrize("bad", ["abc", -3, None, [], {"x": 1}])
def test_invalid_override_falls_back_to_default(monkeypatch, bad):
    monkeypatch.setattr(settings, "initial_run_cooldown_minutes", 30)
    pol = irp.read_initial_run_policy("olx", {"initial_run": {"cooldown_minutes": bad}})
    assert pol.cooldown_minutes == 30


def test_debounce_max_is_never_below_min(monkeypatch):
    monkeypatch.setattr(settings, "initial_run_debounce_min_seconds", 100)
    monkeypatch.setattr(settings, "initial_run_debounce_max_seconds", 10)
    pol = irp.read_initial_run_policy("olx", {})
    assert pol.debounce_max_seconds >= pol.debounce_min_seconds == 100


def test_debounce_delay_stays_inside_window():
    pol = irp.InitialRunPolicy(cooldown_minutes=30, debounce_min_seconds=90, debounce_max_seconds=120)
    rng = random.Random(7)
    delays = {irp.debounce_delay_seconds(pol, rng) for _ in range(200)}
    assert min(delays) >= 90 and max(delays) <= 120
    assert len(delays) > 5  # jitter real, nao um valor fixo


def test_cooldown_remaining():
    pol = irp.InitialRunPolicy(cooldown_minutes=30, debounce_min_seconds=90, debounce_max_seconds=120)

    assert irp.cooldown_remaining(None, NOW, pol) == timedelta(0)
    assert irp.cooldown_remaining(NOW - timedelta(minutes=31), NOW, pol) == timedelta(0)
    assert irp.cooldown_remaining(NOW - timedelta(minutes=10), NOW, pol) == timedelta(minutes=20)
    # naive datetime (sqlite) e tratado como UTC
    assert irp.cooldown_remaining((NOW - timedelta(minutes=10)).replace(tzinfo=None), NOW, pol) == timedelta(minutes=20)


def test_cooldown_zero_disables_gate():
    pol = irp.InitialRunPolicy(cooldown_minutes=0, debounce_min_seconds=90, debounce_max_seconds=120)
    assert irp.cooldown_remaining(NOW, NOW, pol) == timedelta(0)


def test_reason_and_priority_helpers():
    assert irp.is_initial_run_reason("wishlist_created") is True
    assert irp.is_initial_run_reason(" WISHLIST_CREATED ") is True
    assert irp.is_initial_run_reason("queue") is False
    assert irp.is_initial_run_reason(None) is False
    assert irp.run_reason_for_job_priority(irp.INITIAL_RUN_PRIORITY) == irp.INITIAL_RUN_REASON
    assert irp.run_reason_for_job_priority(0) is None
    assert irp.run_reason_for_job_priority(None) is None
