from types import SimpleNamespace

from app.services.source_execution_helpers import build_run_payload


def test_build_run_payload_success_shape():
    payload = build_run_payload(
        run_summary={"status": "ok"},
        run_reason="scheduler",
        hybrid_browser_used=False,
        hybrid_blocked=False,
        hybrid_blocked_status=None,
        thumb_present=10,
        thumb_rate=0.5,
    )

    assert payload["run_summary"] == {"status": "ok"}
    assert payload["run_reason"] == "scheduler"
    assert payload["thumb_present"] == 10
    assert payload["thumb_rate"] == 0.5
    assert "backoff_minutes" not in payload


def test_build_run_payload_error_shape():
    payload = build_run_payload(
        run_summary={"status": "err"},
        run_reason="admin",
        hybrid_browser_used=True,
        hybrid_blocked=True,
        hybrid_blocked_status=403,
        backoff_minutes=15,
        webmotors_diag={"bucket": "BLOCKED"},
        dual_report="/tmp/report.json",
    )

    assert payload["hybrid_browser_used"] is True
    assert payload["hybrid_blocked"] is True
    assert payload["hybrid_blocked_status"] == 403
    assert payload["backoff_minutes"] == 15
    assert payload["webmotors_diag"]["bucket"] == "BLOCKED"
    assert payload["dual_report"].endswith("report.json")
