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


def test_include_browser_adds_playwright_strategies(monkeypatch):
    monkeypatch.setattr(probe, "get_source", lambda _s: SimpleNamespace(build_url=lambda q: f"https://plugin/{q}"))
    out = probe.build_strategies("civic si", include_browser=True)
    names = [x.name for x in out]
    assert "playwright_domcontentloaded" in names
    assert "playwright_networkidle" in names
    assert "playwright_wait_scroll" in names


def test_brand_model_url_for_civic_si():
    assert probe._brand_model_url("civic si") == "https://lista.mercadolivre.com.br/veiculos/carros-caminhonetes/honda/civic"


def test_json_results_diagnostics():
    out = probe._json_diagnostics('{"results":[{"id":"1","permalink":"https://carro.mercadolivre.com.br/MLB-1"}]}')
    assert out["json_detected"] is True
    assert out["json_results_count"] == 1


def test_json_error_diagnostics():
    out = probe._json_diagnostics('{"error":"forbidden","message":"denied"}')
    assert out["json_detected"] is True
    assert out["json_error_message"] == "forbidden"


def test_include_browser_false_does_not_call_playwright(monkeypatch):
    monkeypatch.setattr(probe, "build_strategies", lambda _q, include_browser=False: [probe.ProbeStrategy("s1", "https://x")])
    monkeypatch.setattr(probe, "get_browser_manager", lambda: (_ for _ in ()).throw(AssertionError("should not call browser")))
    monkeypatch.setattr(probe, "unified_fetch", lambda *_a, **_k: SimpleNamespace(content="<html></html>", method="http", duration_ms=1, final_url="https://x"))
    report = probe.run_probe("civic si", include_browser=False)
    assert report["summary_status"] in {"INCONCLUSIVE", "WARN"}


def test_playwright_unavailable_becomes_skipped(monkeypatch):
    monkeypatch.setattr(probe, "build_strategies", lambda _q, include_browser=False: [probe.ProbeStrategy("playwright_domcontentloaded", "https://x", kind="playwright", browser_wait_until="domcontentloaded")])
    monkeypatch.setattr(probe, "get_browser_manager", lambda: (_ for _ in ()).throw(RuntimeError("no pw")))
    report = probe.run_probe("civic si", include_browser=True)
    assert report["strategies"][0]["skipped"] is True
    assert report["strategies"][0]["reason"] == "playwright_unavailable"


def test_scoring_prefers_json_over_shell(monkeypatch):
    monkeypatch.setattr(probe, "build_strategies", lambda _q, include_browser=False: [probe.ProbeStrategy("json", "https://x"), probe.ProbeStrategy("shell", "https://y")])

    def _fetch(url, *_a, **_k):
        if "x" in url:
            return SimpleNamespace(content='{"results":[{"id":"1"}]}', method="http", duration_ms=1, final_url=url)
        return SimpleNamespace(content="<html><title>| Mercado Livre</title>" + ("a" * 4000) + "</html>", method="http", duration_ms=1, final_url=url)

    monkeypatch.setattr(probe, "unified_fetch", _fetch)
    report = probe.run_probe("civic si")
    assert report["recommended_strategy"] == "json"


def test_shell_without_links_not_recommended(monkeypatch):
    monkeypatch.setattr(probe, "build_strategies", lambda _q, include_browser=False: [probe.ProbeStrategy("shell", "https://x")])
    monkeypatch.setattr(probe, "unified_fetch", lambda *_a, **_k: SimpleNamespace(content="<html><title>| Mercado Livre</title>" + ("a" * 4000) + "</html>", method="http", duration_ms=1, final_url="https://x"))
    report = probe.run_probe("civic si")
    assert report["recommended_strategy"] == ""


def test_capture_dir_writes_only_when_provided(monkeypatch, tmp_path):
    monkeypatch.setattr(probe, "build_strategies", lambda _q, include_browser=False: [probe.ProbeStrategy("s1", "https://x")])
    monkeypatch.setattr(probe, "unified_fetch", lambda *_a, **_k: SimpleNamespace(content="<html><body>x</body></html>", method="http", duration_ms=1, final_url="https://x"))
    report_no = probe.run_probe("civic")
    assert "capture_path" not in report_no["strategies"][0]
    report_yes = probe.run_probe("civic", capture_dir=str(tmp_path))
    assert "capture_path" in report_yes["strategies"][0]


def test_playwright_wait_scroll_runs_actions(monkeypatch):
    class FakePage:
        def __init__(self):
            self.calls = []
            self.url = "https://final"

        def goto(self, *args, **kwargs):
            self.calls.append(("goto", args, kwargs))

        def wait_for_timeout(self, ms):
            self.calls.append(("wait", ms))

        def evaluate(self, script):
            self.calls.append(("eval", script))

        def content(self):
            return "<html><body>ok</body></html>"

        def close(self):
            self.calls.append(("close",))

    class FakeContext:
        def __init__(self, page):
            self.page = page

        def new_page(self):
            return self.page

    class FakeBM:
        def __init__(self, page):
            self.page = page

        def fetch_html_with_actions(self, **kwargs):
            p = self.page
            p.goto(kwargs["url"], wait_until=kwargs["wait_until"], timeout=kwargs["timeout_ms"])
            p.wait_for_timeout(kwargs["extra_wait_ms"])
            p.evaluate("window.scrollTo({top: 600, behavior: 'smooth'})")
            p.wait_for_timeout(1500)
            p.evaluate("window.scrollTo({top: 1200, behavior: 'smooth'})")
            p.wait_for_timeout(2000)
            html = p.content()
            return SimpleNamespace(html=html, final_url=p.url)

    page = FakePage()
    bm = FakeBM(page)
    monkeypatch.setattr(probe, "get_browser_manager", lambda: bm)
    out = probe._fetch_with_playwright(probe.ProbeStrategy("playwright_wait_scroll", "https://x", kind="playwright", browser_wait_scroll=True), "mercadolivre")
    assert out["fetch_ok"] is True
    assert any(c[0] == "wait" and c[1] == 3000 for c in page.calls)
    assert any(c[0] == "eval" for c in page.calls)


def test_playwright_domcontentloaded_does_not_call_scroll(monkeypatch):
    class FakeBM:
        def fetch_html(self, **kwargs):
            return SimpleNamespace(html="<html></html>", final_url=kwargs["url"])

        def fetch_html_with_actions(self, **kwargs):
            raise AssertionError("should not call actions")

    monkeypatch.setattr(probe, "get_browser_manager", lambda: FakeBM())
    out = probe._fetch_with_playwright(probe.ProbeStrategy("playwright_domcontentloaded", "https://x", kind="playwright", browser_wait_until="domcontentloaded"), "mercadolivre")
    assert out["fetch_ok"] is True


def test_strategy_error_does_not_break_report(monkeypatch):
    monkeypatch.setattr(probe, "build_strategies", lambda _q, include_browser=False: [probe.ProbeStrategy("playwright_wait_scroll", "https://x", kind="playwright", browser_wait_scroll=True)])

    class BrokenBM:
        def fetch_html_with_actions(self, **kwargs):
            raise TimeoutError("timeout")

    monkeypatch.setattr(probe, "get_browser_manager", lambda: BrokenBM())
    report = probe.run_probe("civic", include_browser=True)
    assert report["strategies"][0]["fetch_ok"] is False
    assert "TimeoutError" in report["strategies"][0]["error"]
