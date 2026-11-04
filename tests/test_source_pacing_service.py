"""Pacing por source: desligado por padrao, rajadas menores, mais espacadas e irregulares."""

import random
from datetime import datetime, timedelta, timezone

from app.services import source_pacing_service as sp

T0 = datetime(2026, 10, 19, 8, 0, tzinfo=timezone.utc)


def test_jittered_minutes_is_stable_bounded_and_varies():
    assert sp.jittered_minutes(720, T0, 0) == 720
    assert sp.jittered_minutes(720, None, 25) == 720
    assert sp.jittered_minutes(0, T0, 25) == 0
    assert sp.jittered_minutes(720, T0, 25) == sp.jittered_minutes(720, T0, 25)  # estavel entre ticks
    vals = {sp.jittered_minutes(720, T0 + timedelta(hours=i), 25) for i in range(40)}
    assert len(vals) > 20 and all(540 <= v <= 900 for v in vals)  # 720 +-25%


def test_pick_groups_rotates_least_recently_served():
    urls = ["a", "b", "c", "d", "e"]
    assert sp.pick_groups(urls, last_served={}, max_groups=0) == urls
    assert sp.pick_groups(urls, last_served={}, max_groups=9) == urls
    assert sp.pick_groups(urls, last_served={}, max_groups=2) == ["a", "b"]
    cursor = {"a": "2026-10-19T08:00", "b": "2026-10-19T08:00", "c": "2026-10-18T08:00"}
    assert sp.pick_groups(urls, last_served=cursor, max_groups=2) == ["d", "e"]  # nunca atendidas primeiro
    later = {**cursor, "d": "2026-10-19T09:00", "e": "2026-10-19T09:00"}
    assert sp.pick_groups(urls, last_served=later, max_groups=2) == ["a", "c"]  # c (mais antiga) e a (empate, 1a)


def test_rotation_covers_every_group():
    urls = [f"u{i}" for i in range(10)]
    cursor: dict = {}
    seen: list = []
    for i in range(4):
        picked = sp.pick_groups(urls, last_served=cursor, max_groups=3)
        assert len(picked) == 3
        seen += picked
        cursor = sp.mark_served(cursor, picked, now=T0 + timedelta(hours=i), keep=urls)
    assert set(seen) == set(urls)


# --- Fronteiras, padroes e entradas invalidas (guiado por teste de mutacao) -----------------
import dataclasses
import hashlib

import pytest


class _FakeRng:
    """Registra o uso para provar que o rng injetado (e nao o global) e quem decide."""

    def __init__(self):
        self.shuffled = None
        self.uniform_args = None

    def shuffle(self, items):
        self.shuffled = list(items)
        items.reverse()

    def uniform(self, lo, hi):
        self.uniform_args = (lo, hi)
        return 123.5


def test_pacing_defaults_are_neutral_frozen_and_slotted():
    p = sp.Pacing()
    assert (p.inter_group_delay_s, p.shuffle_groups, p.max_groups_per_run, p.sched_jitter_pct) == ((0.0, 0.0), False, 0, 0.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.shuffle_groups = True  # type: ignore[misc]
    assert not hasattr(p, "__dict__")  # slots=True


@pytest.mark.parametrize(
    "kwargs, enabled",
    [
        ({}, False),
        ({"inter_group_delay_s": (0.0, 5.0)}, True),
        ({"inter_group_delay_s": (0.0, 0.0)}, False),
        ({"shuffle_groups": True}, True),
        ({"max_groups_per_run": 1}, True),
        ({"sched_jitter_pct": 0.1}, True),
    ],
)
def test_pacing_enabled_when_any_single_feature_is_on(kwargs, enabled):
    assert sp.Pacing(**kwargs).enabled is enabled  # cada campo sozinho liga o pacing (OR, nao AND)


@pytest.mark.parametrize(
    "delay, expected",
    [
        ([40, 150], (40.0, 150.0)),
        ((150, 40), (40.0, 150.0)),  # tupla e ordenada
        ([-5, 10], (0.0, 10.0)),  # negativo vira 0
        ([-5, -2], (0.0, 0.0)),
        ([0, 99999], (0.0, 600.0)),  # teto de 600s
        ([700, 900], (600.0, 600.0)),
        (30, (30.0, 30.0)),
        (2.5, (2.5, 2.5)),
        (-3, (0.0, 0.0)),
        (True, (0.0, 0.0)),  # bool nao e numero
        ([5], (0.0, 0.0)),  # tamanho != 2 e ignorado
        ([1, 2, 3], (0.0, 0.0)),
        (["a", "b"], (0.0, 0.0)),
        ([None, 3], (0.0, 0.0)),
        ("abc", (0.0, 0.0)),
        (None, (0.0, 0.0)),
    ],
)
def test_read_pacing_inter_group_delay(delay, expected):
    assert sp.read_pacing({"pacing": {"inter_group_delay_s": delay}}).inter_group_delay_s == expected


@pytest.mark.parametrize(
    "raw, expected",
    [("3", 3), (3, 3), (2.9, 2), (0, 0), (-2, 0), ("x", 0), (None, 0), ([], 0), (1, 1)],
)
def test_read_pacing_max_groups_per_run(raw, expected):
    assert sp.read_pacing({"pacing": {"max_groups_per_run": raw}}).max_groups_per_run == expected


@pytest.mark.parametrize(
    "raw, expected",
    [(25, 25.0), ("12.5", 12.5), (50, 50.0), (51, 50.0), (999, 50.0), (-5, 0.0), (0, 0.0), ("x", 0.0), (None, 0.0), ([], 0.0)],
)
def test_read_pacing_sched_jitter_pct_is_clamped(raw, expected):
    assert sp.read_pacing({"pacing": {"sched_jitter_pct": raw}}).sched_jitter_pct == expected


def _expected_jitter(minutes, last, pct):
    digest = hashlib.sha256(last.astimezone(timezone.utc).isoformat().encode()).digest()
    frac = int.from_bytes(digest[:4], "big") / 0xFFFFFFFF
    return max(1, round(minutes * (1.0 + (pct / 100.0) * (2.0 * frac - 1.0))))


@pytest.mark.parametrize("minutes, pct", [(720, 25), (100, 50), (60, 10), (1000, 1)])
def test_jittered_minutes_matches_the_documented_formula(minutes, pct):
    for i in range(12):
        t = T0 + timedelta(hours=i, minutes=7 * i)
        got = sp.jittered_minutes(minutes, t, pct)
        assert got == _expected_jitter(minutes, t, pct)
        assert round(minutes * (1 - pct / 100)) <= got <= round(minutes * (1 + pct / 100))


def test_jittered_minutes_passthrough_cases_and_floor_of_one():
    assert sp.jittered_minutes(-5, T0, 25) == -5  # minutes <= 0 volta como veio
    assert sp.jittered_minutes(720, T0, -5) == 720  # pct <= 0
    assert sp.jittered_minutes(720, None, 25) == 720
    assert all(sp.jittered_minutes(1, T0 + timedelta(minutes=i), 50) >= 1 for i in range(30))
    assert sp.jittered_minutes(1, T0, 0.0001) == 1  # pct positivo minimo ainda e aplicado


def test_pick_groups_boundaries_and_input_is_not_mutated():
    urls = ["a", "b", "c"]
    assert sp.pick_groups(urls, last_served={}, max_groups=3) == urls  # len == max
    assert sp.pick_groups(urls, last_served={}, max_groups=3) is not urls  # copia
    assert sp.pick_groups(urls, last_served={}, max_groups=-1) == urls
    assert sp.pick_groups(urls, last_served={}, max_groups=1) == ["a"]
    assert sp.pick_groups(urls, last_served={"a": "2", "b": "1", "c": "3"}, max_groups=1) == ["b"]
    assert urls == ["a", "b", "c"]


def test_order_groups_uses_injected_rng_and_returns_a_copy():
    urls = ["a", "b", "c"]
    rng = _FakeRng()
    assert sp.order_groups(urls, shuffle=True, rng=rng) == ["c", "b", "a"]
    assert rng.shuffled == ["a", "b", "c"]
    assert urls == ["a", "b", "c"]  # entrada intacta
    same = sp.order_groups(urls, shuffle=False, rng=rng)
    assert same == urls and same is not urls


def test_delay_seconds_draws_between_bounds_from_injected_rng():
    rng = _FakeRng()
    assert sp.delay_seconds(sp.Pacing(inter_group_delay_s=(10.0, 20.0)), rng) == 123.5
    assert rng.uniform_args == (10.0, 20.0)
    rng2 = _FakeRng()
    assert sp.delay_seconds(sp.Pacing(inter_group_delay_s=(0.0, 0.0)), rng2) == 0.0
    assert rng2.uniform_args is None  # hi == 0: nem sorteia
    assert sp.delay_seconds(sp.Pacing(inter_group_delay_s=(7.0, 7.0)), _FakeRng()) == 123.5


def test_mark_served_stamps_utc_iso_coerces_values_and_keeps_only_alive():
    br = timezone(timedelta(hours=-3))
    now = datetime(2026, 10, 19, 5, 0, tzinfo=br)  # = 08:00Z
    out = sp.mark_served({"keep": 5, "dead": "x"}, ["new"], now=now, keep=["keep", "new"])
    assert out == {"keep": "5", "new": "2026-10-19T08:00:00+00:00"}
    assert sp.mark_served(None, [], now=T0, keep=[]) == {}
    assert sp.CURSOR_KV_PREFIX == "source_group_cursor:"


def test_pacing_helpers_with_keyword_only_arguments():
    with pytest.raises(TypeError):
        sp.pick_groups(["a"], {}, 1)  # type: ignore[misc]
    with pytest.raises(TypeError):
        sp.order_groups(["a"], True)  # type: ignore[misc]
    with pytest.raises(TypeError):
        sp.mark_served({}, [], T0, [])  # type: ignore[misc]
