from app.services.mercadolivre_strategy_probe import (
    ProbeOptions,
    _analyze_content,
    _score,
    build_mercadolivre_strategy_urls,
    run_probe,
)


def test_build_urls_includes_known_strategies():
    rows = build_mercadolivre_strategy_urls("civic si")
    names = {r["strategy"] for r in rows}
    assert "plugin_build_url" in names
    assert "v2_build_search_url" in names
    assert "lista_generic_slug" in names
    assert "lista_vehicle_slug" in names
    assert "api_with_category" in names
    assert "api_without_category" in names
    assert "api_category_first" in names


def test_civic_si_urls():
    rows = {r["strategy"]: r for r in build_mercadolivre_strategy_urls("civic si")}
    assert "lista.mercadolivre.com.br/veiculos/carros-caminhonetes/civic-si" in rows["plugin_build_url"]["url"]
    assert "api.mercadolibre.com/sites/MLB/search" in rows["v2_build_search_url"]["url"]
    if "lista_vehicle_brand_model" in rows:
        assert "/honda/civic" in rows["lista_vehicle_brand_model"]["url"]


def test_diagnose_json_results():
    r = _analyze_content('{"results": [{"id": 1}]}')
    assert r["json_detected"] is True
    assert r["json_results_count"] == 1


def test_html_shell_scoring():
    html = "<html><head><title>| Mercado Livre</title></head><body>Mercado Livre" + ("x" * 3500) + "</body></html>"
    base = {"fetch_blocked": False, "content_length": len(html)}
    base.update(_analyze_content(html))
    assert "mercado_livre_page" in base["html_diagnostics"]["signals"]
    assert _score(base) <= 0


def test_aggregation_statuses(monkeypatch):
    import app.services.mercadolivre_strategy_probe as mod

    def fake_attempt(url_row, fetch_strategy, options):
        score = 100 if "api_with_category" == url_row["strategy"] else -10
        return {
            "url_strategy": url_row["strategy"], "fetch_strategy": fetch_strategy, "url": url_row["url"],
            "fetch_ok": True, "fetch_blocked": score < 0, "http_status": None, "error": "", "fetch_method": "x", "duration_ms": 1,
            "final_url": "", "content_type": "", "content_length": 10, "json_detected": False, "json_results_count": None,
            "json_error_message": "", "html_diagnostics": {"title": "", "canonical_url": "", "og_url": "", "selector_counts": {"cards_count": 0, "a_mlb_links": 0, "a_vehicle_links": 0}, "signals": [], "sample_links": []},
            "useful_data_score": score, "recommended": False,
        }

    monkeypatch.setattr(mod, "_run_attempt", fake_attempt)
    result = run_probe("civic si", ProbeOptions(include_browser=False))
    assert result["summary_status"] == "OK"
    assert result["recommended_strategy"]


def test_cli_no_browser_paths(monkeypatch, tmp_path):
    import app.services.mercadolivre_strategy_probe as mod

    def fake_attempt(url_row, fetch_strategy, options):
        return {
            "url_strategy": url_row["strategy"], "fetch_strategy": fetch_strategy, "url": url_row["url"],
            "fetch_ok": fetch_strategy != "playwright_domcontentloaded", "fetch_blocked": False, "http_status": None, "error": "", "fetch_method": "x", "duration_ms": 1,
            "final_url": "", "content_type": "", "content_length": 10, "json_detected": False, "json_results_count": None,
            "json_error_message": "", "html_diagnostics": {"title": "", "canonical_url": "", "og_url": "", "selector_counts": {"cards_count": 0, "a_mlb_links": 0, "a_vehicle_links": 0}, "signals": [], "sample_links": []},
            "useful_data_score": 1, "recommended": False,
        }

    monkeypatch.setattr(mod, "_run_attempt", fake_attempt)
    out = run_probe("civic si", ProbeOptions(include_browser=False, capture_dir=str(tmp_path)))
    assert all("playwright" not in a["fetch_strategy"] for a in out["attempts"])
