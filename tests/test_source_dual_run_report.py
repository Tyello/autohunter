from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.source_dual_run_report import (
    build_dual_run_report,
    compare_items,
    normalize_item_for_compare,
    render_dual_run_report_markdown,
)
from scripts import source_dual_run_report as script


def test_normalize_item_for_compare_defensive():
    out = normalize_item_for_compare({"title": "  Civic  ", "price": "R$ 80.000", "location": " São Paulo , SP "})
    assert out["title"] == "Civic"
    assert out["price"] == "80000"
    assert out["city"] == "São Paulo"
    assert out["uf"] == "SP"
    assert out["external_id"] == ""
    assert out["thumbnail"] == ""


def test_compare_items_matching_and_diffs():
    v1 = [{"external_id": "A1", "title": "Civic", "price": "100", "year": "2020"}, {"external_id": "A2", "title": "Corolla", "price": "200"}]
    v2 = [{"external_id": "A1", "title": "Civic SI", "price": "120", "year": "2020"}, {"external_id": "A3", "title": "Golf", "price": "300"}]
    cmp = compare_items(v1, v2)
    assert cmp["matched_count"] == 1
    assert cmp["only_v1_count"] == 1
    assert cmp["only_v2_count"] == 1
    assert cmp["field_diffs_count"] == 1
    assert "price" in cmp["field_diff_examples"][0]["diff_fields"]


@pytest.mark.parametrize(
    "v1_count,v2_count,expected",
    [
        (2, 0, "FAIL"),
        (10, 6, "WARN"),
        (10, 9, "OK"),
    ],
)
def test_summary_status(v1_count, v2_count, expected):
    report = build_dual_run_report("mercadolivre", "https://x", [{"id": i} for i in range(v1_count)], [{"id": i} for i in range(v2_count)])
    assert report["summary_status"] == expected


def test_render_markdown_contains_expected_sections():
    report = build_dual_run_report("mercadolivre", "https://x", [{"external_id": "a"}], [{"external_id": "b"}])
    md = render_dual_run_report_markdown(report)
    assert "mercadolivre" in md
    assert "v1_count" in md
    assert "v2_count" in md
    assert "status" in md
    assert "only_v1_examples" in md


def test_script_parse_args_validation_and_success_path(monkeypatch, capsys):
    with pytest.raises(SystemExit):
        script.parse_args(["olx", "--query", "x"])

    class FakeV2:
        def scrape(self, url, ctx):
            return SimpleNamespace(items=[{"external_id": "1", "title": "A"}])

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
    assert '"source": "mercadolivre"' in out
