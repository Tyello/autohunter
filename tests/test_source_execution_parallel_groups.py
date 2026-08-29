from __future__ import annotations

import threading
import time
import uuid
from types import SimpleNamespace

from app.core.settings import settings
from app.services import source_execution_service as svc

from tests.test_source_execution_service import _add_cfg, _last_run, _plugin, _setup_run, _wishlist


def _wishlists(n: int, *, prefix: str = "q"):
    return [_wishlist(query=f"{prefix}{i}") for i in range(n)]


def _urls_for(plugin, wishlists):
    return [plugin.build_url(w.query) for w in wishlists]


def _ok_result(**overrides):
    base = {
        "ok": True,
        "found": 0,
        "inserted": 0,
        "matched": 0,
        "queued": 0,
        "already_notified": 0,
        "reason_buckets": {},
        "thumb_present": 0,
        "runtime_impl": "v2_canary",
        "adapter_meta": {"raw_count": 0, "normalized_count": 0},
    }
    base.update(overrides)
    return base


def test_req001_one_failing_group_does_not_block_others(db, monkeypatch):
    plugin = _plugin("mercadolivre")
    wishlists = _wishlists(3)
    urls = _urls_for(plugin, wishlists)
    _add_cfg(db)
    db.commit()
    _setup_run(monkeypatch, wishlists=wishlists, plugin=plugin)

    calls = []
    lock = threading.Lock()

    def _scrape(_db, _job_name, _dispatch, url, *, ctx, wishlist=None, health=None):
        with lock:
            calls.append(url)
        if url == urls[1]:
            return {"ok": False, "reason": "error", "error": "boom", "url": url, "is_bug": False}
        return _ok_result()

    for _ in range(5):
        calls.clear()
        monkeypatch.setattr(svc, "scrape_ingest_match", _scrape)

        res = svc.run_source_for_all_wishlists(db, "mercadolivre", kind="scheduler", force=True, ignore_backoff=True)

        assert set(calls) == set(urls), "all 3 groups must be invoked regardless of group 2's failure"
        assert res["ok"] is False
        assert res["status"] == "error"
        assert res["url"] == urls[1]


def test_req002_reported_failure_follows_original_order_not_completion_order(db, monkeypatch):
    plugin = _plugin("mercadolivre")
    wishlists = _wishlists(3)
    urls = _urls_for(plugin, wishlists)
    _add_cfg(db)
    db.commit()
    _setup_run(monkeypatch, wishlists=wishlists, plugin=plugin)

    def _scrape(_db, _job_name, _dispatch, url, *, ctx, wishlist=None, health=None):
        if url == urls[0]:
            time.sleep(0.15)
            return {"ok": False, "reason": "error", "error": "slow_first_group", "url": url, "is_bug": False}
        if url == urls[2]:
            return {"ok": False, "reason": "error", "error": "fast_last_group", "url": url, "is_bug": False}
        return _ok_result()

    monkeypatch.setattr(svc, "scrape_ingest_match", _scrape)

    res = svc.run_source_for_all_wishlists(db, "mercadolivre", kind="scheduler", force=True, ignore_backoff=True)

    assert res["ok"] is False
    assert res["url"] == urls[0], "the group at original position 0 must win even though it finishes last"
    assert res["error"] == "slow_first_group"

    persisted_last_error = _last_run(db, "mercadolivre").payload["run_summary"]["last_error"]
    assert persisted_last_error["message"] == "slow_first_group", (
        "the persisted run_summary's last_error must also reflect the first failure by "
        "original order, not whichever failing group's health was merged last"
    )


def test_req003_each_group_opens_and_closes_its_own_session(db, monkeypatch):
    plugin = _plugin("mercadolivre")
    wishlists = _wishlists(3)
    _add_cfg(db)
    db.commit()
    _setup_run(monkeypatch, wishlists=wishlists, plugin=plugin)
    monkeypatch.setattr(svc, "scrape_ingest_match", lambda *_a, **_k: _ok_result())

    opened: list[int] = []
    closed: list[int] = []
    lock = threading.Lock()
    real_session_local = svc.SessionLocal

    def _tracking_session_local():
        session = real_session_local()
        with lock:
            opened.append(id(session))
        orig_close = session.close

        def _close():
            with lock:
                closed.append(id(session))
            orig_close()

        session.close = _close
        return session

    monkeypatch.setattr(svc, "SessionLocal", _tracking_session_local)

    res = svc.run_source_for_all_wishlists(db, "mercadolivre", kind="scheduler", force=True, ignore_backoff=True)

    assert res["ok"] is True
    assert len(opened) == 3
    assert len(set(opened)) == 3, "each group must open a distinct Session"
    assert id(db) not in opened, "groups must never reuse the caller's Session"
    assert set(closed) == set(opened), "every thread-local Session must be closed"


def test_req004_concurrency_never_exceeds_max_workers(db, monkeypatch):
    source = f"cap_test_{uuid.uuid4().hex[:8]}"
    plugin = _plugin(source)
    wishlists = _wishlists(5)
    _add_cfg(db, source=source)
    db.commit()
    _setup_run(monkeypatch, source=source, wishlists=wishlists, plugin=plugin)
    monkeypatch.setattr(settings, "source_group_max_workers", 2)
    monkeypatch.setattr(settings, "source_max_concurrent_per_source", 10)

    in_flight = 0
    peak = 0
    lock = threading.Lock()

    def _scrape(_db, _job_name, _dispatch, _url, *, ctx, wishlist=None, health=None):
        nonlocal in_flight, peak
        with lock:
            in_flight += 1
            peak = max(peak, in_flight)
        time.sleep(0.05)
        with lock:
            in_flight -= 1
        return _ok_result()

    monkeypatch.setattr(svc, "scrape_ingest_match", _scrape)

    res = svc.run_source_for_all_wishlists(db, source, kind="scheduler", force=True, ignore_backoff=True)

    assert res["ok"] is True
    assert peak <= 2, f"peak in-flight groups ({peak}) exceeded source_group_max_workers (2)"


def test_req005_per_source_semaphore_serializes_concurrent_calls(monkeypatch):
    source = f"sem_test_{uuid.uuid4().hex[:8]}"
    plugin = _plugin(source)
    monkeypatch.setattr(settings, "source_max_concurrent_per_source", 1)

    setup_db = svc.SessionLocal()
    try:
        _add_cfg(setup_db, source=source)
        setup_db.commit()
    finally:
        setup_db.close()

    intervals: list[tuple[float, float]] = []
    lock = threading.Lock()

    def _scrape(_db, _job_name, _dispatch, _url, *, ctx, wishlist=None, health=None):
        start = time.monotonic()
        time.sleep(0.08)
        end = time.monotonic()
        with lock:
            intervals.append((start, end))
        return _ok_result()

    monkeypatch.setattr(svc, "ensure_source_configs", lambda _db: None)
    monkeypatch.setattr(svc, "get_source", lambda _src: plugin if _src == source else None)
    monkeypatch.setattr(svc, "scrape_ingest_match", _scrape)
    monkeypatch.setattr(svc, "reconcile_listing_activity_for_source_run", lambda *_a, **_k: SimpleNamespace(to_dict=lambda: {"ok": True}))
    monkeypatch.setattr(svc, "log", lambda *_a, **_k: None)
    monkeypatch.setattr(svc, "emit_event", lambda *_a, **_k: None)

    def _run_call(wishlist_query: str, out: list):
        session = svc.SessionLocal()
        try:
            monkeypatch.setattr(
                svc,
                "_wishlist_eligibility_snapshot",
                lambda _db, _src: ([_wishlist(query=wishlist_query)], {"active_wishlists": 1}),
                raising=False,
            )
            out.append(svc.run_source_for_all_wishlists(session, source, kind="scheduler", force=True, ignore_backoff=True))
        finally:
            session.close()

    results_a: list = []
    results_b: list = []
    t1 = threading.Thread(target=_run_call, args=("call_a", results_a))
    t2 = threading.Thread(target=_run_call, args=("call_b", results_b))
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert len(intervals) == 2
    (s1, e1), (s2, e2) = sorted(intervals)
    assert e1 <= s2, "the per-source semaphore must serialize concurrent scrape calls for the same source"


def test_req007_aggregation_across_groups_matches_sequential_sum(db, monkeypatch):
    plugin = _plugin("mercadolivre")
    wishlists = _wishlists(4)
    urls = _urls_for(plugin, wishlists)
    _add_cfg(db)
    db.commit()
    _setup_run(monkeypatch, wishlists=wishlists, plugin=plugin)

    per_group = {
        urls[0]: {"found": 3, "inserted": 1, "matched": 1, "queued": 1, "already_notified": 0, "thumb_present": 2, "reason_buckets": {"queued": 1}},
        urls[1]: {"found": 5, "inserted": 2, "matched": 2, "queued": 1, "already_notified": 1, "thumb_present": 3, "reason_buckets": {"filtered_price": 1}},
        urls[2]: {"found": 0, "inserted": 0, "matched": 0, "queued": 0, "already_notified": 0, "thumb_present": 0, "reason_buckets": {}},
        urls[3]: {"found": 2, "inserted": 1, "matched": 0, "queued": 0, "already_notified": 0, "thumb_present": 1, "reason_buckets": {"queued": 1}},
    }

    def _scrape(_db, _job_name, _dispatch, url, *, ctx, wishlist=None, health=None):
        return _ok_result(**per_group[url])

    monkeypatch.setattr(svc, "scrape_ingest_match", _scrape)

    res = svc.run_source_for_all_wishlists(db, "mercadolivre", kind="scheduler", force=True, ignore_backoff=True)

    assert res["ok"] is True
    assert res["found"] == sum(v["found"] for v in per_group.values())
    assert res["inserted"] == sum(v["inserted"] for v in per_group.values())
    assert res["matched"] == sum(v["matched"] for v in per_group.values())
    assert res["queued"] == sum(v["queued"] for v in per_group.values())
    assert res["already_notified"] == sum(v["already_notified"] for v in per_group.values())
    assert res["reason_buckets"] == {"queued": 2, "filtered_price": 1}


def test_req006_parallel_tick_latency_beats_sequential_baseline(db, monkeypatch):
    """Benchmark evidence (not a strict perf-regression gate): with N=8 groups costing 0.05s
    each to scrape, the parallel tick (max_workers=4) must land well under a naive sequential
    baseline of N * 0.05s. This is the "measure tick latency before/after" requirement.
    """
    source = f"latency_test_{uuid.uuid4().hex[:8]}"
    plugin = _plugin(source)
    n = 8
    wishlists = _wishlists(n)
    _add_cfg(db, source=source)
    db.commit()
    _setup_run(monkeypatch, source=source, wishlists=wishlists, plugin=plugin)
    monkeypatch.setattr(settings, "source_group_max_workers", 4)
    monkeypatch.setattr(settings, "source_max_concurrent_per_source", 10)

    sleep_s = 0.05

    def _scrape(_db, _job_name, _dispatch, _url, *, ctx, wishlist=None, health=None):
        time.sleep(sleep_s)
        return _ok_result()

    # Baseline: cost of scraping the same N groups one-by-one (what the old sequential
    # loop would have paid), measured outside the function under test.
    baseline_start = time.monotonic()
    for _ in range(n):
        time.sleep(sleep_s)
    sequential_ms = (time.monotonic() - baseline_start) * 1000

    monkeypatch.setattr(svc, "scrape_ingest_match", _scrape)

    res = svc.run_source_for_all_wishlists(db, source, kind="scheduler", force=True, ignore_backoff=True)

    assert res["ok"] is True
    parallel_ms = res["duration_ms"]
    assert parallel_ms < sequential_ms * 0.6, (
        f"parallel tick ({parallel_ms}ms) should be well under 60% of the sequential "
        f"baseline ({sequential_ms:.1f}ms) with source_group_max_workers=4 for N={n} groups"
    )
