from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.models.source_run import SourceRun
from app.services.auction_source_history_service import build_auction_source_history


def _mk_run(db, source, kind, payload, created_at=None):
    run = SourceRun(
        id=uuid.uuid4(),
        source=source,
        kind=kind,
        status="ok",
        payload=payload,
        created_at=created_at or datetime.now(timezone.utc),
    )
    db.add(run)
    db.commit()
    return run


def test_build_history_returns_empty_cycles_when_no_runs(db, monkeypatch):
    monkeypatch.setattr(
        "app.services.auction_source_history_service.build_auction_quality_report",
        lambda db, source: {"sources": []},
    )
    result = build_auction_source_history(db, "mega_auctions")
    assert result["cycles"] == []
    assert result["current_score"] is None


def test_build_history_skips_runs_without_auction_summary(db, monkeypatch):
    monkeypatch.setattr(
        "app.services.auction_source_history_service.build_auction_quality_report",
        lambda db, source: {"sources": []},
    )
    _mk_run(db, "mega_auctions", "manual", {"other": "data"})
    result = build_auction_source_history(db, "mega_auctions")
    assert result["cycles"] == []


def test_build_history_ignores_non_manual_runs(db, monkeypatch):
    monkeypatch.setattr(
        "app.services.auction_source_history_service.build_auction_quality_report",
        lambda db, source: {"sources": []},
    )
    _mk_run(db, "mega_auctions", "scheduled", {"auction_summary": {"found": 5}})
    result = build_auction_source_history(db, "mega_auctions")
    assert result["cycles"] == []


def test_build_history_extracts_summary_fields_and_score(db, monkeypatch):
    monkeypatch.setattr(
        "app.services.auction_source_history_service.build_auction_quality_report",
        lambda db, source: {"sources": [{"quality_score": 87}]},
    )
    _mk_run(db, "mega_auctions", "manual", {"auction_summary": {"found": 10, "inserted": 3, "updated": 1}})

    result = build_auction_source_history(db, "mega_auctions")

    assert result["current_score"] == 87
    assert len(result["cycles"]) == 1
    assert result["cycles"][0]["found"] == 10
    assert result["cycles"][0]["inserted"] == 3
    assert result["cycles"][0]["score"] == 87


def test_build_history_respects_limit(db, monkeypatch):
    monkeypatch.setattr(
        "app.services.auction_source_history_service.build_auction_quality_report",
        lambda db, source: {"sources": []},
    )
    for i in range(5):
        _mk_run(db, "mega_auctions", "manual", {"auction_summary": {"found": i}})

    result = build_auction_source_history(db, "mega_auctions", limit=2)
    assert len(result["cycles"]) == 2
