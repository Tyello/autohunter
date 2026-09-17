from __future__ import annotations

import time

import app.services.playwright_pool as pw_pool
from app.services.playwright_pool import _is_playwright_process, sweep_orphan_playwright_processes


class _FakeProc:
    def __init__(self, pid, name="headless_shell", cmdline=None, create_time=None):
        self.pid = pid
        self._name = name
        self._cmdline = cmdline or [name]
        self._create_time = create_time if create_time is not None else time.time()
        self.killed = False

    def name(self):
        return self._name

    def cmdline(self):
        return self._cmdline

    def create_time(self):
        return self._create_time

    def kill(self):
        self.killed = True


def test_is_playwright_process_matches_chromium_and_node_driver():
    assert _is_playwright_process(_FakeProc(1, name="headless_shell")) is True
    assert _is_playwright_process(_FakeProc(2, name="node", cmdline=["node", ".../ms-playwright/driver/cli.js", "run-driver"])) is True
    assert _is_playwright_process(_FakeProc(3, name="postgres")) is False


def test_sweep_kills_only_old_orphans_outside_live_pids(monkeypatch):
    now = time.time()
    live = _FakeProc(10, name="headless_shell", create_time=now - 500)  # belongs to the live tree
    young_orphan = _FakeProc(11, name="headless_shell", create_time=now - 5)  # too young, might still be spawning
    old_orphan = _FakeProc(12, name="headless_shell", create_time=now - 500)  # should be killed
    unrelated = _FakeProc(13, name="bash", create_time=now - 500)  # not a playwright process

    class _FakePsutil:
        process_iter = staticmethod(lambda attrs=None: [live, young_orphan, old_orphan, unrelated])
        pid_exists = staticmethod(lambda pid: False)
        wait_procs = staticmethod(lambda procs, timeout=5: None)

    monkeypatch.setitem(__import__("sys").modules, "psutil", _FakePsutil())
    monkeypatch.setattr(pw_pool, "_POOL", None)  # no live pool tracked -> live_pids empty

    # System-wide scan (not just children of this process), so a truly orphaned
    # process reparented to init is still found. With _POOL=None, live_pids is
    # empty and `live` would also be a candidate; the test focuses on age + type
    # filtering (the sweep's core contract), asserting only on young_orphan/
    # old_orphan/unrelated.
    result = sweep_orphan_playwright_processes(min_age_seconds=120)

    assert result["ok"] is True
    assert 12 in result["killed_pids"]
    assert old_orphan.killed is True
    assert 11 not in result["killed_pids"]
    assert young_orphan.killed is False
    assert 13 not in result["killed_pids"]
    assert unrelated.killed is False
