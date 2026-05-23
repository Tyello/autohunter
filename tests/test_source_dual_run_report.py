from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.source_dual_run_report import (
    build_dual_run_report,
    compare_items,
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


@pytest.mark.parametrize(
    "v1_count,v2_count,expected_status,expected_reason",
    [
        (0, 0, "INCONCLUSIVE", "both_paths_returned_zero_items"),
        (2, 0, "FAIL", "v2_returned_zero_items_while_v1_found_items"),
        (0, 2, "WARN", "v1_returned_zero_items_while_v2_found_items"),
        (10, 6, "WARN", "count_difference_above_threshold"),
        (10, 9, "OK", "counts_within_threshold"),
    ],
)
def test_summary_status_and_reason(v1_count, v2_count, expected_status, expected_reason):
    report = build_dual_run_report("mercadolivre", "https://x", [{"id": i} for i in range(v1_count)], [{"id": i} for i in range(v2_count)])
    assert report["summary_status"] == expected_status
    assert report["summary_reason"] == expected_reason


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
    assert '"summary_reason": "counts_within_threshold"' in out


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
