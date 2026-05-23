from __future__ import annotations

from types import SimpleNamespace

from app.services import mercadolivre_strategy_probe as probe


def test_build_urls_contains_expected(monkeypatch):
    monkeypatch.setattr(probe, "get_source", lambda _s: SimpleNamespace(build_url=lambda q: f"https://lista.mercadolivre.com.br/veiculos/carros-caminhonetes/{q.replace(' ', '-') }"))
    rows = probe.build_mercadolivre_strategy_urls("civic si")
    names = {r["strategy"] for r in rows}
    assert {"plugin_build_url", "v2_build_search_url", "lista_generic_slug", "lista_vehicle_slug", "api_with_category", "api_without_category", "api_category_first"}.issubset(names)


def test_include_browser_fetchers_present_and_absent():
    with_browser = [f.name for f in probe._build_fetch_strategies(include_browser=True)]
    without_browser = [f.name for f in probe._build_fetch_strategies(include_browser=False)]
    assert "playwright_domcontentloaded" in with_browser
    assert "playwright_networkidle" in with_browser
    assert "playwright_wait_scroll" in with_browser
    assert "playwright_domcontentloaded" not in without_browser
    assert "playwright_networkidle" not in without_browser
    assert "playwright_wait_scroll" not in without_browser


def test_civic_si_urls(monkeypatch):
    monkeypatch.setattr(probe, "get_source", lambda _s: SimpleNamespace(build_url=lambda _q: "https://lista.mercadolivre.com.br/veiculos/carros-caminhonetes/civic-si"))
    rows = {r["strategy"]: r["url"] for r in probe.build_mercadolivre_strategy_urls("civic si")}
    assert "/veiculos/carros-caminhonetes/civic-si" in rows["plugin_build_url"]
    assert "/veiculos/carros-caminhonetes/civic-si" in rows["v2_build_search_url"]
    assert "/honda/civic" in rows["lista_vehicle_brand_model"]


def test_json_diagnostics_results():
    out = probe._json_diagnostics('{"results":[{"id":1}]}')
    assert out["json_detected"] is True and out["json_results_count"] == 1


def test_html_shell_score_non_positive():
    row = {"fetch_blocked": False, "content_length": 7201, "json_results_count": 0, "html_diagnostics": {"selector_counts": {"a_mlb_links": 0, "a_vehicle_links": 0, "li.ui-search-layout__item": 0}, "signals": ["mercado_livre_page"]}}
    assert probe._compute_useful_data_score(row) <= 0


def test_recommended_marks_exact_url_and_fetch(monkeypatch):
    monkeypatch.setattr(
        probe,
        "build_mercadolivre_strategy_urls",
        lambda *_a, **_k: [{"strategy": "same_url_strategy", "url": "https://x", "kind": "html", "source": "manual"}],
    )
    monkeypatch.setattr(
        probe,
        "_build_fetch_strategies",
        lambda include_browser: [
            probe.ProbeFetchStrategy("unified_fetch", "http"),
            probe.ProbeFetchStrategy("playwright_wait_scroll", "playwright", wait_until="domcontentloaded", wait_scroll=True),
        ],
    )

    def _http_fetch(*_a, **_k):
        return SimpleNamespace(content="<html><title>| Mercado Livre</title>" + ("a" * 5000) + "</html>", method="http", final_url="https://x")

    monkeypatch.setattr(probe, "unified_fetch", _http_fetch)
    monkeypatch.setattr(
        probe,
        "_fetch_playwright",
        lambda *_a, **_k: {"content": '<html><ul><li class="ui-search-layout__item">ok</li></ul></html>', "final_url": "https://x", "http_status": None, "content_type": "text/html"},
    )

    report = probe.run_probe("civic", include_browser=True)
    assert isinstance(report["recommended_strategy"], dict)
    assert report["recommended_strategy"]["url_strategy"] == "same_url_strategy"
    assert report["recommended_strategy"]["fetch_strategy"] == "playwright_wait_scroll"
    assert report["recommended_strategy_key"] == "same_url_strategy+playwright_wait_scroll"

    winners = [a for a in report["attempts"] if a["recommended"]]
    assert len(winners) == 1
    assert winners[0]["fetch_strategy"] == "playwright_wait_scroll"


def test_cli_behaviors_capture_and_no_browser(monkeypatch, tmp_path):
    monkeypatch.setattr(probe, "_build_fetch_strategies", lambda include_browser: [probe.ProbeFetchStrategy("unified_fetch", "http")])
    monkeypatch.setattr(probe, "build_mercadolivre_strategy_urls", lambda *_a, **_k: [{"strategy": "s1", "url": "https://x", "kind": "html", "source": "manual"}])
    monkeypatch.setattr(probe, "get_browser_manager", lambda: (_ for _ in ()).throw(AssertionError("no browser")))
    monkeypatch.setattr(probe, "unified_fetch", lambda *_a, **_k: SimpleNamespace(content="<html><title>| Mercado Livre</title></html>", method="http", final_url="https://x"))
    r1 = probe.run_probe("civic", include_browser=False)
    assert "capture_path" not in r1["attempts"][0]
    r2 = probe.run_probe("civic", include_browser=False, capture_dir=str(tmp_path))
    assert "capture_path" in r2["attempts"][0]
