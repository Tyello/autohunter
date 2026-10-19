"""Pacing por source: desligado por padrao, rajadas menores, mais espacadas e irregulares."""

import random
from datetime import datetime, timedelta, timezone

from app.services import source_pacing_service as sp

T0 = datetime(2026, 10, 19, 8, 0, tzinfo=timezone.utc)


def test_default_is_disabled():
    for extra in (None, {}, {"pacing": None}, {"pacing": "x"}, {"pacing": {}}):
        assert sp.read_pacing(extra).enabled is False


def test_read_pacing_parses_and_clamps():
    p = sp.read_pacing({"pacing": {
        "inter_group_delay_s": [150, 40], "shuffle_groups": 1,
        "max_groups_per_run": "3", "sched_jitter_pct": 999,
    }})
    assert p.inter_group_delay_s == (40.0, 150.0)
    assert p.shuffle_groups is True and p.max_groups_per_run == 3
    assert p.sched_jitter_pct == 50.0 and p.enabled


def test_read_pacing_ignores_garbage():
    p = sp.read_pacing({"pacing": {"inter_group_delay_s": "abc", "max_groups_per_run": -4, "sched_jitter_pct": "x"}})
    assert p.inter_group_delay_s == (0.0, 0.0) and p.max_groups_per_run == 0 and p.sched_jitter_pct == 0.0
    assert sp.read_pacing({"pacing": {"inter_group_delay_s": 90}}).inter_group_delay_s == (90.0, 90.0)
    assert sp.read_pacing({"pacing": {"inter_group_delay_s": [0, 99999]}}).inter_group_delay_s[1] == 600.0


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


def test_mark_served_drops_dead_urls():
    out = sp.mark_served({"old": "x", "a": "y"}, ["a", "b"], now=T0, keep=["a", "b"])
    assert set(out) == {"a", "b"} and out["a"].startswith("2026-10-19")


def test_order_and_delay():
    urls = [f"u{i}" for i in range(20)]
    assert sp.order_groups(urls, shuffle=False) == urls
    shuffled = sp.order_groups(urls, shuffle=True, rng=random.Random(1))
    assert sorted(shuffled) == sorted(urls) and shuffled != urls
    assert sp.delay_seconds(sp.Pacing()) == 0.0
    p = sp.Pacing(inter_group_delay_s=(40.0, 150.0))
    d = {round(sp.delay_seconds(p, random.Random(i))) for i in range(30)}
    assert len(d) > 10 and all(40 <= x <= 150 for x in d)
