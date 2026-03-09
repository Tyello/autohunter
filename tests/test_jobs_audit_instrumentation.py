from __future__ import annotations

from types import SimpleNamespace

from app.scheduler import jobs


def test_capture_helper_no_trigger_when_healthy(monkeypatch):
    ctx = SimpleNamespace(source="olx", extra={"_audit_fetch_samples": []})
    called = {"n": 0}

    def _fake(*args, **kwargs):
        called["n"] += 1
        return []

    monkeypatch.setattr(jobs.source_audit_capture_service, "capture_from_runtime_samples", _fake)
    out = jobs._capture_if_needed(
        ctx=ctx,
        found=2,
        listings=[{"external_id": "1", "url": "https://x", "title": "ok", "price": 1, "location": "SP", "year": 2020, "mileage_km": 1000, "thumbnail_url": "https://i"}],
        stage="post_ingest",
        reason="post_scrape_check",
    )
    assert out == []
    assert called["n"] == 0


def test_capture_helper_trigger_on_missing_critical(monkeypatch):
    ctx = SimpleNamespace(source="olx", extra={"_audit_fetch_samples": [{"kind": "listing", "url": "https://olx", "payload": "<html></html>", "ext": ".html"}]})

    monkeypatch.setattr(
        jobs.source_audit_capture_service,
        "capture_from_runtime_samples",
        lambda **kwargs: [],
    )
    out = jobs._capture_if_needed(
        ctx=ctx,
        found=1,
        listings=[{"external_id": "1", "url": "https://x"}],
        stage="post_ingest",
        reason="post_scrape_check",
    )
    assert out == []
