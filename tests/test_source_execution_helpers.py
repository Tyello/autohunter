from types import SimpleNamespace

import pytest

from app.scrapers.base import FetchBlocked
from app.scrapers.scraper_base.metrics import PipelineMetrics
from app.scrapers.scraper_base.scraper import ScraperResult
from app.services.source_execution_helpers import build_run_payload, build_scrape_dispatch
from app.sources.flags import SourceImplFlags
from app.sources.types import ScrapeContext


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


def test_build_run_payload_includes_runtime_impl_and_adapter_meta():
    payload = build_run_payload(
        run_summary={"status": "ok"},
        run_reason="admin",
        hybrid_browser_used=False,
        hybrid_blocked=False,
        hybrid_blocked_status=None,
        runtime_impl="v2_canary",
        adapter_meta={"impl": "v2_canary", "raw_count": 10, "normalized_count": 10},
    )

    assert payload["runtime_impl"] == "v2_canary"
    assert payload["adapter_meta"]["impl"] == "v2_canary"


class _FakeV2Scraper:
    def __init__(self, result: ScraperResult):
        self._result = result

    def scrape(self, _search_url, _ctx):
        return self._result


def _canary_dispatch(result: ScraperResult):
    flags = SourceImplFlags(impl="v1", canary_v2_enabled=True)
    return build_scrape_dispatch(
        src="mercadolivre",
        flags=flags,
        plugin=SimpleNamespace(scrape=None),
        v2_scraper=_FakeV2Scraper(result),
        ad_to_listing=lambda ad: {"external_id": ad.external_id},
    )


def test_scrape_dispatch_canary_v2_reraises_fetch_blocked(monkeypatch):
    monkeypatch.setattr(
        "app.services.source_execution_helpers.settings.enable_playwright", True, raising=False
    )
    metrics = PipelineMetrics(source="mercadolivre", fetch_error="Blocked (200) for url=x reason=ml_security_or_captcha_page")
    result = ScraperResult(listings=[], metrics=metrics, warnings=["Fetch blocked: x"], blocked=True)
    dispatch = _canary_dispatch(result)
    ctx = ScrapeContext(source="mercadolivre", browser_fallback_enabled=True)

    with pytest.raises(FetchBlocked) as exc_info:
        dispatch("https://lista.mercadolivre.com.br/veiculos/carros-caminhonetes/civic-si", ctx)

    assert "ml_security_or_captcha_page" in str(exc_info.value)


def test_scrape_dispatch_canary_v2_does_not_raise_when_not_blocked(monkeypatch):
    monkeypatch.setattr(
        "app.services.source_execution_helpers.settings.enable_playwright", True, raising=False
    )
    metrics = PipelineMetrics(source="mercadolivre")
    result = ScraperResult(listings=[], metrics=metrics, warnings=[], blocked=False)
    dispatch = _canary_dispatch(result)
    ctx = ScrapeContext(source="mercadolivre", browser_fallback_enabled=True)

    listings = dispatch("https://lista.mercadolivre.com.br/veiculos/carros-caminhonetes/civic-si", ctx)

    assert listings == []
