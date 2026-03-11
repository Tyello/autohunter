import json
from types import SimpleNamespace

import pytest

from app.scrapers.base import FetchBlocked
from app.scrapers.webmotors import scrape_webmotors
from app.sources.types import ScrapeContext


HTML_WITH_ITEM = '''
<html><body>
<a href="https://www.webmotors.com.br/comprar/honda/civic/2019/123456">ver</a>
<h2>Honda Civic</h2>
<div>R$ 99.000</div>
</body></html>
'''


def test_webmotors_fallback_proxy_to_direct(monkeypatch):
    calls = []

    def _fake_fetch(url, *, ctx, **kwargs):
        calls.append(ctx.proxy_server)
        if ctx.proxy_server:
            raise RuntimeError("proxy tunnel failed")
        return SimpleNamespace(html=HTML_WITH_ITEM, final_url=url)

    monkeypatch.setattr("app.scrapers.webmotors.fetch_html_browser", _fake_fetch)

    ctx = ScrapeContext(source="webmotors", proxy_server="http://proxy.local:8080")
    out = scrape_webmotors("https://www.webmotors.com.br/carros/estoque", ctx)

    assert len(out) == 1
    assert calls[0] == "http://proxy.local:8080"
    assert calls[1] is None


def test_webmotors_does_not_mask_parser_failure_as_empty(monkeypatch):
    def _fake_fetch(url, *, ctx, **kwargs):
        return SimpleNamespace(html="<html><body>layout mudou</body></html>", final_url=url)

    monkeypatch.setattr("app.scrapers.webmotors.fetch_html_browser", _fake_fetch)

    ctx = ScrapeContext(source="webmotors")
    with pytest.raises(RuntimeError) as exc:
        scrape_webmotors("https://www.webmotors.com.br/carros/estoque", ctx)

    assert "WM_DIAG::" in str(exc.value)
    assert '"bucket":"PARSER"' in str(exc.value)


def test_webmotors_zero_results_returns_empty(monkeypatch):
    def _fake_fetch(url, *, ctx, **kwargs):
        return SimpleNamespace(html="<html><body>Nenhum veículo encontrado</body></html>", final_url=url)

    monkeypatch.setattr("app.scrapers.webmotors.fetch_html_browser", _fake_fetch)

    ctx = ScrapeContext(source="webmotors")
    out = scrape_webmotors("https://www.webmotors.com.br/carros/estoque", ctx)
    assert out == []


def test_webmotors_blocked_error_preserves_diagnostic(monkeypatch):
    def _fake_fetch(url, *, ctx, **kwargs):
        raise FetchBlocked(403, url, reason="bot_challenge")

    monkeypatch.setattr("app.scrapers.webmotors.fetch_html_browser", _fake_fetch)

    ctx = ScrapeContext(source="webmotors")
    with pytest.raises(FetchBlocked) as exc:
        scrape_webmotors("https://www.webmotors.com.br/carros/estoque", ctx)

    assert exc.value.reason is not None
    assert "WM_DIAG::" in exc.value.reason


def test_webmotors_soft_block_200_is_not_treated_as_empty(monkeypatch):
    html = """
    <html><head><title>Just a moment...</title></head>
    <body><div>Checking your browser before accessing Webmotors</div></body></html>
    """

    def _fake_fetch(url, *, ctx, **kwargs):
        return SimpleNamespace(html=html, final_url=url)

    monkeypatch.setattr("app.scrapers.webmotors.fetch_html_browser", _fake_fetch)

    ctx = ScrapeContext(source="webmotors")
    with pytest.raises(FetchBlocked) as exc:
        scrape_webmotors("https://www.webmotors.com.br/carros/estoque", ctx)

    assert exc.value.status_code == 200
    assert '"bucket":"BLOCKED"' in (exc.value.reason or "")
    assert '"detected_signals":["challenge_cloudflare","soft_block_interstitial"' in (exc.value.reason or "")


def test_webmotors_debug_artifacts_created_when_enabled(monkeypatch, tmp_path):
    html = "<html><head><title>Access denied</title></head><body>verify you are human</body></html>"

    def _fake_fetch(url, *, ctx, **kwargs):
        return SimpleNamespace(html=html, final_url=url)

    monkeypatch.setattr("app.scrapers.webmotors.fetch_html_browser", _fake_fetch)
    monkeypatch.setattr("app.scrapers.webmotors_debug.settings.webmotors_debug_dir", str(tmp_path / "wm_debug"))
    monkeypatch.setattr("app.scrapers.webmotors_debug.settings.webmotors_debug_max_artifacts", 10)
    monkeypatch.setattr("app.scrapers.webmotors_debug.settings.webmotors_debug_text_snippet_chars", 120)

    ctx = ScrapeContext(source="webmotors", extra={"webmotors_debug_capture": True})
    with pytest.raises(FetchBlocked):
        scrape_webmotors("https://www.webmotors.com.br/carros/estoque", ctx)

    runs = list((tmp_path / "wm_debug").glob("*"))
    assert runs
    metadata_file = runs[0] / "metadata.json"
    assert metadata_file.exists()
    data = json.loads(metadata_file.read_text(encoding="utf-8"))
    assert data["status"] == "blocked"
    assert data["cards_found"] == 0
    assert data["url_initial"].startswith("https://www.webmotors.com.br/")
    assert "blocked_reason" in data
