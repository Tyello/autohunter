from datetime import datetime, timedelta, timezone

from app.models.autopilot_finding import AutopilotFinding
from app.models.source_config import SourceConfig
from app.models.source_run import SourceRun
from app.models.source_state import SourceState
from app.services import autopilot_service


def _add_runs(db, now, source, statuses, *, url="https://lista.mercadolivre.com.br/veiculos/carros-caminhonetes/civic-si", runtime_impl=None):
    for i, status in enumerate(statuses):
        payload = {"runtime_impl": runtime_impl} if runtime_impl else None
        db.add(
            SourceRun(
                source=source,
                kind="scheduler",
                status=status,
                url=url,
                payload=payload,
                created_at=now - timedelta(minutes=i + 1),
            )
        )


def _blocked_spike(db, now, source="mercadolivre"):
    cands = autopilot_service.build_candidates(db, now=now)
    return next(c for c in cands if c.kind == "blocked_spike" and c.source == source)


def test_mercadolivre_canary_blocked_spike_actions_are_canary_aware(db, monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(autopilot_service.settings, "enable_playwright", True)
    monkeypatch.setattr(autopilot_service, "get_active_source_queue_partial_index_details", lambda _db: {"ok": True})
    db.add(
        SourceConfig(
            source="mercadolivre",
            is_enabled=True,
            sched_minutes=30,
            browser_fallback_enabled=True,
            force_browser=False,
            extra={"impl": "v1", "mercadolivre_v2_canary_enabled": True},
        )
    )
    db.add(SourceState(source="mercadolivre", last_status="skipped:backoff", next_allowed_at=now + timedelta(hours=1)))
    _add_runs(db, now, "mercadolivre", ["blocked", "blocked", "success", "success", "success"], runtime_impl="v2_canary")
    db.commit()

    cand = _blocked_spike(db, now)
    text = cand.suggested_actions
    assert cand.severity == "warn"
    assert "/admin sources canary mercadolivre report" in text
    assert "browser_fallback já está ativo" in text
    assert "não habilitar force_browser" in text
    assert "habilitar browser_fallback/force_browser" not in text
    assert cand.evidence["source_context"]["canary_effective"] is True
    assert cand.evidence["source_context"]["runtime_impl"] == "v2_canary"
    alert = autopilot_service.format_alert(
        AutopilotFinding(kind=cand.kind, source=cand.source, severity=cand.severity, title=cand.title, evidence=cand.evidence, suggested_actions=cand.suggested_actions)
    )
    assert "canary_effective: True" in alert
    assert "correlation_key: source:mercadolivre:blocked_backoff" in alert


def test_mercadolivre_without_canary_can_suggest_fallback_and_canary(db, monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(autopilot_service.settings, "enable_playwright", True)
    monkeypatch.setattr(autopilot_service, "get_active_source_queue_partial_index_details", lambda _db: {"ok": True})
    db.add(
        SourceConfig(
            source="mercadolivre",
            is_enabled=True,
            sched_minutes=30,
            browser_fallback_enabled=False,
            extra={"impl": "v1", "mercadolivre_v2_canary_enabled": False},
        )
    )
    _add_runs(db, now, "mercadolivre", ["blocked", "blocked", "success", "success", "success"])
    db.commit()

    cand = _blocked_spike(db, now)
    assert "avaliar canary V2" in cand.suggested_actions
    assert "habilitar browser_fallback" in cand.suggested_actions
    assert cand.evidence["source_context"]["canary_effective"] is False


def test_non_mercadolivre_keeps_generic_blocked_spike_actions(db, monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(autopilot_service, "get_active_source_queue_partial_index_details", lambda _db: {"ok": True})
    _add_runs(db, now, "olx", ["blocked", "blocked", "success", "success", "success"], url="https://olx.example/civic")
    db.commit()

    cand = _blocked_spike(db, now, source="olx")
    assert "habilitar browser_fallback/force_browser" in cand.suggested_actions
    assert "/admin sources canary mercadolivre report" not in cand.suggested_actions


def test_blocked_spike_deduplicates_sample_urls(db, monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(autopilot_service, "get_active_source_queue_partial_index_details", lambda _db: {"ok": True})
    url = "https://lista.mercadolivre.com.br/veiculos/carros-caminhonetes/civic-si"
    _add_runs(db, now, "mercadolivre", ["blocked", "blocked", "success", "success", "success"], url=url)
    db.commit()

    cand = _blocked_spike(db, now)
    assert cand.evidence["sample_urls"] == [url]
    alert = autopilot_service.format_alert(
        AutopilotFinding(kind=cand.kind, source=cand.source, severity=cand.severity, title=cand.title, evidence=cand.evidence, suggested_actions=cand.suggested_actions)
    )
    assert alert.count(url) == 1


def test_mercadolivre_blocked_severity_uses_success_context(db, monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(autopilot_service, "get_active_source_queue_partial_index_details", lambda _db: {"ok": True})
    _add_runs(db, now, "mercadolivre", ["blocked", "blocked", "success", "success", "success"])
    db.commit()
    assert _blocked_spike(db, now).severity == "warn"

    db.query(SourceRun).delete()
    db.add(SourceState(source="mercadolivre", consecutive_blocks=5))
    _add_runs(db, now, "mercadolivre", ["blocked", "blocked", "blocked", "blocked", "blocked"])
    db.commit()
    assert _blocked_spike(db, now).severity == "error"
