from __future__ import annotations

from types import SimpleNamespace

from app.services import mercadolivre_strategy_probe as probe


def test_build_strategies_contains_expected_names(monkeypatch):
    monkeypatch.setattr(probe, "get_source", lambda _s: SimpleNamespace(build_url=lambda q: f"https://plugin/{q}"))
    out = probe.build_strategies("civic si")
    names = [x.name for x in out]
    assert "html_listing_current" in names
    assert "api_search_current" in names
    assert "plugin_build_url" in names


def test_json_results_diagnostics():
    out = probe._json_diagnostics('{"results":[{"id":"1","permalink":"https://carro.mercadolivre.com.br/MLB-1"}]}')
    assert out["json_detected"] is True
    assert out["json_results_count"] == 1


def test_json_error_diagnostics():
    out = probe._json_diagnostics('{"error":"forbidden","message":"denied"}')
    assert out["json_detected"] is True
    assert out["json_error_message"] == "forbidden"


def test_run_probe_inconclusive_shell(monkeypatch):
    monkeypatch.setattr(probe, "build_strategies", lambda _q: [probe.ProbeStrategy("s1", "https://x")])
    monkeypatch.setattr(probe, "unified_fetch", lambda *_a, **_k: SimpleNamespace(content="<html><title>| Mercado Livre</title></html>", method="http", duration_ms=3))
    report = probe.run_probe("civic si")
    assert report["summary_status"] == "INCONCLUSIVE"


def test_run_probe_fail_all_blocked(monkeypatch):
    monkeypatch.setattr(probe, "build_strategies", lambda _q: [probe.ProbeStrategy("s1", "https://x")])

    def _raise(*_a, **_k):
        raise RuntimeError("FetchBlocked 403")

    monkeypatch.setattr(probe, "unified_fetch", _raise)
    report = probe.run_probe("civic si")
    assert report["summary_status"] == "FAIL"


def test_run_probe_ok_and_recommended(monkeypatch):
    monkeypatch.setattr(probe, "build_strategies", lambda _q: [probe.ProbeStrategy("s1", "https://x")])
    monkeypatch.setattr(probe, "unified_fetch", lambda *_a, **_k: SimpleNamespace(content='{"results":[{"id":"1"}]}', method="http", duration_ms=1))
    report = probe.run_probe("civic si")
    assert report["summary_status"] == "OK"
    assert report["recommended_strategy"] == "s1"


def test_capture_dir_writes_only_when_provided(monkeypatch, tmp_path):
    monkeypatch.setattr(probe, "build_strategies", lambda _q: [probe.ProbeStrategy("s1", "https://x")])
    monkeypatch.setattr(probe, "unified_fetch", lambda *_a, **_k: SimpleNamespace(content="<html><body>x</body></html>", method="http", duration_ms=1))
    report_no = probe.run_probe("civic")
    assert "capture_path" not in report_no["strategies"][0]
    report_yes = probe.run_probe("civic", capture_dir=str(tmp_path))
    assert "capture_path" in report_yes["strategies"][0]
