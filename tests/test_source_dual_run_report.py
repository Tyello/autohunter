from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.source_dual_run_report import (
    build_dual_run_report,
    build_mercadolivre_probe_hints,
    compare_items,
    diagnose_mercadolivre_html,
    normalize_item_for_compare,
    render_dual_run_report_markdown,
)
from scripts import source_dual_run_report as script


def test_script_bootstraps_project_root_before_app_imports():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "source_dual_run_report.py"
    content = script_path.read_text(encoding="utf-8")

    bootstrap_idx = content.index("ROOT = Path(__file__).resolve().parents[1]")
    sys_path_insert_idx = content.index("sys.path.insert(0, str(ROOT))")
    app_import_idx = content.index("from app.scrapers.sources import get_scraper")

    assert bootstrap_idx < app_import_idx
    assert sys_path_insert_idx < app_import_idx


def test_normalize_item_for_compare_defensive():
    out = normalize_item_for_compare({"title": "  Civic  ", "price": "R$ 80.000", "location": " São Paulo , SP "})
    assert out["title"] == "Civic"
    assert out["price"] == "80000"
    assert out["city"] == "São Paulo"
    assert out["uf"] == "SP"


def test_compare_items_matching_and_diffs():
    v1 = [{"external_id": "A1", "title": "Civic", "price": "100", "year": "2020"}, {"external_id": "A2", "title": "Corolla", "price": "200"}]
    v2 = [{"external_id": "A1", "title": "Civic SI", "price": "120", "year": "2020"}, {"external_id": "A3", "title": "Golf", "price": "300"}]
    cmp = compare_items(v1, v2)
    assert cmp["matched_count"] == 1
    assert cmp["only_v1_count"] == 1
    assert cmp["only_v2_count"] == 1
    assert cmp["field_diffs_count"] == 1
    assert cmp["blocking_field_diffs_count"] >= 1


@pytest.mark.parametrize(
    "v1_count,v2_count,expected_status,expected_reason",
    [
        (0, 0, "INCONCLUSIVE", "both_paths_returned_zero_items"),
        (2, 0, "FAIL", "v2_returned_zero_items_while_v1_found_items"),
        (0, 2, "WARN", "v1_returned_zero_items_while_v2_found_items"),
        (10, 6, "WARN", "unique_id_mismatch_between_paths"),
        (10, 9, "WARN", "unique_id_mismatch_between_paths"),
    ],
)
def test_summary_status_and_reason(v1_count, v2_count, expected_status, expected_reason):
    report = build_dual_run_report("mercadolivre", "https://x", [{"id": i} for i in range(v1_count)], [{"id": i} for i in range(v2_count)])
    assert report["summary_status"] == expected_status
    assert report["summary_reason"] == expected_reason


def test_v1_duplicates_v2_unique_same_ids_unique_parity_ok():
    v1 = [{"external_id": "A1", "title": "Civic", "price": "100"}, {"external_id": "A1", "title": "Civic", "price": "100"}]
    v2 = [{"external_id": "A1", "title": "Civic", "price": "100"}]
    report = build_dual_run_report("mercadolivre", "https://x", v1, v2)
    assert report["only_v1_count"] == 0
    assert report["only_v2_count"] == 0
    assert report["v1_duplicate_count"] == 1
    assert report["v2_duplicate_count"] == 0
    assert report["summary_status"] == "OK"
    assert report["summary_reason"] == "unique_parity_ok"


def test_year_diff_with_v2_filled_is_enrichment():
    v1 = [{"external_id": "A1", "year": ""}]
    v2 = [{"external_id": "A1", "year": "2014"}]
    report = build_dual_run_report("mercadolivre", "https://x", v1, v2)
    diff = report["field_diff_examples"][0]["diff_fields"]["year"]
    assert diff["classification"] == "v2_enrichment"
    assert report["enrichment_field_diffs_count"] == 1
    assert report["summary_status"] == "OK"
    assert report["summary_reason"] == "unique_parity_ok_enrichment_only"


def test_price_diff_is_blocking():
    v1 = [{"external_id": "A1", "price": "100"}]
    v2 = [{"external_id": "A1", "price": "999"}]
    report = build_dual_run_report("mercadolivre", "https://x", v1, v2)
    diff = report["field_diff_examples"][0]["diff_fields"]["price"]
    assert diff["classification"] == "blocking"
    assert report["blocking_field_diffs_count"] == 1
    assert report["summary_status"] == "WARN"
    assert report["summary_reason"] == "blocking_field_diffs_between_paths"


def test_title_diff_is_blocking_and_warn():
    v1 = [{"external_id": "A1", "title": "Civic"}]
    v2 = [{"external_id": "A1", "title": "Civic SI"}]
    report = build_dual_run_report("mercadolivre", "https://x", v1, v2)
    diff = report["field_diff_examples"][0]["diff_fields"]["title"]
    assert diff["classification"] == "blocking"
    assert report["summary_status"] == "WARN"
    assert report["summary_reason"] == "blocking_field_diffs_between_paths"


def test_thumbnail_v2_filled_is_enrichment():
    v1 = [{"external_id": "A1", "thumbnail": ""}]
    v2 = [{"external_id": "A1", "thumbnail": "http://img"}]
    report = build_dual_run_report("mercadolivre", "https://x", v1, v2)
    diff = report["field_diff_examples"][0]["diff_fields"]["thumbnail"]
    assert diff["classification"] == "v2_enrichment"


def test_real_id_difference_keeps_warn():
    v1 = [{"external_id": "A1"}]
    v2 = [{"external_id": "A2"}]
    report = build_dual_run_report("mercadolivre", "https://x", v1, v2)
    assert report["only_v1_count"] > 0
    assert report["summary_status"] in {"WARN", "FAIL"}


def test_summary_status_fails_when_any_side_errors():
    report = build_dual_run_report("mercadolivre", "https://x", [], [{"id": 1}], v1_error="RuntimeError: boom")
    assert report["summary_status"] == "FAIL"
    assert report["summary_reason"] == "path_execution_error"
    assert "v1_error" in report


def test_render_markdown_contains_summary_reason_and_error_fields():
    report = build_dual_run_report("mercadolivre", "https://x", [], [], v1_error="RuntimeError: v1", v2_error="RuntimeError: v2")
    report["v2_blocked"] = True
    report["v2_warnings"] = ["challenge"]
    md = render_dual_run_report_markdown(report)
    assert "summary_reason" in md
    assert "v2_blocked" in md
    assert "v2_warnings" in md
    assert "v1_error" in md
    assert "v2_error" in md


def test_script_parse_args_validation_and_success_path(monkeypatch, capsys):
    with pytest.raises(SystemExit):
        script.parse_args(["olx", "--query", "x"])

    class FakeV2:
        def scrape(self, url, ctx):
            return SimpleNamespace(listings=[{"external_id": "1", "title": "A"}], warnings=[], blocked=False)

    plugin = SimpleNamespace(
        default_extra={"foo": "bar"},
        build_url=lambda q: f"https://example.com/?q={q}",
        scrape=lambda search_url, ctx=None: [{"external_id": "1", "title": "A"}],
    )

    monkeypatch.setattr(script, "get_source", lambda _s: plugin)
    monkeypatch.setattr(script, "get_scraper", lambda _s: FakeV2())

    rc = script.main(["mercadolivre", "--query", "civic", "--format", "json", "--limit", "5"])
    out = capsys.readouterr().out
    assert rc == 0
    assert '"summary_reason": "unique_parity_ok"' in out


def test_script_generates_report_when_v1_fails(monkeypatch, capsys):
    class FakeV2:
        def scrape(self, url, ctx):
            return SimpleNamespace(listings=[{"external_id": "1"}], warnings=["ok"], blocked=False)

    plugin = SimpleNamespace(
        default_extra={},
        build_url=lambda q: f"https://example.com/?q={q}",
        scrape=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("v1 broke")),
    )

    monkeypatch.setattr(script, "get_source", lambda _s: plugin)
    monkeypatch.setattr(script, "get_scraper", lambda _s: FakeV2())

    rc = script.main(["mercadolivre", "--query", "civic", "--format", "json"])
    out = capsys.readouterr().out
    assert rc == 0
    assert '"v1_error": "RuntimeError: v1 broke"' in out


def test_script_generates_report_when_v2_fails(monkeypatch, capsys):
    class FakeV2:
        def scrape(self, url, ctx):
            raise RuntimeError("v2 broke")

    plugin = SimpleNamespace(
        default_extra={},
        build_url=lambda q: f"https://example.com/?q={q}",
        scrape=lambda *_args, **_kwargs: [{"external_id": "1"}],
    )

    monkeypatch.setattr(script, "get_source", lambda _s: plugin)
    monkeypatch.setattr(script, "get_scraper", lambda _s: FakeV2())

    rc = script.main(["mercadolivre", "--query", "civic", "--format", "json"])
    out = capsys.readouterr().out
    assert rc == 0
    assert '"v2_error": "RuntimeError: v2 broke"' in out


def test_zero_zero_includes_inconclusive_hints():
    report = build_dual_run_report("mercadolivre", "https://lista.mercadolivre.com.br/veiculos/carros-caminhonetes/civic-si", [], [])
    assert report["summary_status"] == "INCONCLUSIVE"
    assert report["summary_reason"] == "both_paths_returned_zero_items"
    hints = report["diagnostics"]["hints"]
    assert "both_paths_zero_items" in hints
    assert "not_safe_to_flip_to_v2" in hints


def test_v2_metrics_raw_items_found_gt_zero_adds_parse_gap_hint():
    metrics = SimpleNamespace(raw_items_found=3)
    report = build_dual_run_report("mercadolivre", "https://x", [{"id": 1}], [], v2_metrics=metrics)
    hints = report["diagnostics"]["hints"]
    assert "v2_extracted_raw_but_parsed_zero" in hints


def test_v2_metrics_raw_items_found_zero_adds_fetch_extract_hint():
    metrics = SimpleNamespace(raw_items_found=0)
    report = build_dual_run_report("mercadolivre", "https://x", [{"id": 1}], [], v2_metrics=metrics)
    hints = report["diagnostics"]["hints"]
    assert "v2_extracted_zero_raw_items" in hints


def test_v2_blocked_adds_hint():
    report = build_dual_run_report("mercadolivre", "https://x", [], [], v2_blocked=True)
    assert "v2_blocked" in report["diagnostics"]["hints"]


def test_script_json_includes_diagnostics_metrics(monkeypatch, capsys):
    class FakeV2:
        def scrape(self, url, ctx):
            metrics = SimpleNamespace(fetch_method="http", raw_items_found=2, items_valid=0)
            return SimpleNamespace(listings=[], warnings=[], blocked=False, metrics=metrics)

    plugin = SimpleNamespace(
        default_extra={},
        build_url=lambda q: f"https://example.com/?q={q}",
        scrape=lambda *_args, **_kwargs: [],
    )

    monkeypatch.setattr(script, "get_source", lambda _s: plugin)
    monkeypatch.setattr(script, "get_scraper", lambda _s: FakeV2())

    rc = script.main(["mercadolivre", "--query", "civic", "--format", "json"])
    out = capsys.readouterr().out
    assert rc == 0
    assert '"diagnostics"' in out
    assert '"v2_metrics"' in out
    assert '"fetch_method": "http"' in out


def test_markdown_includes_diagnostics_hints():
    report = build_dual_run_report("mercadolivre", "https://x", [], [], v2_warnings=["challenge"])
    md = render_dual_run_report_markdown(report)
    assert "diagnostics_hints" in md


def test_diagnose_mercadolivre_html_with_cards():
    html = """
    <html><head><title>Carros | Mercado Livre</title><link rel="canonical" href="https://lista.mercadolivre.com.br/veiculos"/></head>
    <body><li class="ui-search-layout__item"><a href="https://lista.mercadolivre.com.br/veiculos/carro/MLB-123">x</a></li></body></html>
    """
    out = diagnose_mercadolivre_html(html)
    assert out["selector_counts"]["li.ui-search-layout__item"] == 1
    assert "has_mlb_links" in out["signals"]
    assert "has_vehicle_links" in out["signals"]


def test_diagnose_mercadolivre_html_zero_results_signal():
    out = diagnose_mercadolivre_html("<html><body>Não encontramos resultados para sua busca</body></html>")
    assert "zero_results" in out["signals"] or "no_results" in out["signals"]


def test_diagnose_mercadolivre_html_access_denied_signal():
    out = diagnose_mercadolivre_html("<html><body>Access to this page has been denied</body></html>")
    assert "access_denied" in out["signals"] or "bot_challenge" in out["signals"]


def test_probe_hints_links_without_cards():
    html = "<html><body><a href='https://carro.mercadolivre.com.br/MLB-123'>Civic</a></body></html>"
    diag = diagnose_mercadolivre_html(html)
    hints = build_mercadolivre_probe_hints(0, diag)
    assert "ml_links_present_but_card_selectors_missing" in hints


def test_script_probe_fetch_and_capture(monkeypatch, capsys, tmp_path):
    class FakeV2:
        def scrape(self, url, ctx):
            return SimpleNamespace(listings=[], warnings=[], blocked=False, metrics=SimpleNamespace(raw_items_found=0))

    plugin = SimpleNamespace(default_extra={}, build_url=lambda q: "https://lista.mercadolivre.com.br/veiculos/civic", scrape=lambda *_args, **_kwargs: [])
    monkeypatch.setattr(script, "get_source", lambda _s: plugin)
    monkeypatch.setattr(script, "get_scraper", lambda _s: FakeV2())
    monkeypatch.setattr(
        script,
        "unified_fetch",
        lambda *_args, **_kwargs: SimpleNamespace(content="<html><title>ML</title></html>", method="hybrid"),
    )
    capture = tmp_path / "captures" / "ml.html"
    rc = script.main(["mercadolivre", "--query", "civic", "--format", "json", "--probe-fetch", "--capture-html", str(capture)])
    out = capsys.readouterr().out
    assert rc == 0
    assert '"fetch_probe"' in out
    assert capture.exists()
