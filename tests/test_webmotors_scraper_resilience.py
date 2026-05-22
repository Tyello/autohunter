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


def test_webmotors_curl_cffi_flag_absent_does_not_attempt(monkeypatch):
    called = {"curl": 0}
    monkeypatch.setattr("app.scrapers.webmotors._fetch_webmotors_html_curl_cffi", lambda *_a, **_k: called.__setitem__("curl", 1))
    monkeypatch.setattr("app.scrapers.webmotors.fetch_html_browser", lambda url, *, ctx, **kwargs: SimpleNamespace(html=HTML_WITH_ITEM, final_url=url))
    scrape_webmotors("https://www.webmotors.com.br/carros/estoque", ScrapeContext(source="webmotors"))
    assert called["curl"] == 0


def test_webmotors_curl_cffi_flag_false_does_not_attempt(monkeypatch):
    called = {"curl": 0}
    monkeypatch.setattr("app.scrapers.webmotors._fetch_webmotors_html_curl_cffi", lambda *_a, **_k: called.__setitem__("curl", 1))
    monkeypatch.setattr("app.scrapers.webmotors.fetch_html_browser", lambda url, *, ctx, **kwargs: SimpleNamespace(html=HTML_WITH_ITEM, final_url=url))
    scrape_webmotors("https://www.webmotors.com.br/carros/estoque", ScrapeContext(source="webmotors", extra={"webmotors_curl_cffi_enabled": False}))
    assert called["curl"] == 0


def test_webmotors_curl_cffi_flag_true_attempts(monkeypatch):
    called = {"curl": 0}
    monkeypatch.setattr("app.scrapers.webmotors._fetch_webmotors_html_curl_cffi", lambda *_a, **_k: (called.__setitem__("curl", 1) or (200, HTML_WITH_ITEM)))
    monkeypatch.setattr("app.scrapers.webmotors.fetch_html_browser", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("browser should not be called")))
    out = scrape_webmotors("https://www.webmotors.com.br/carros/estoque", ScrapeContext(source="webmotors", extra={"webmotors_curl_cffi_enabled": True}))
    assert called["curl"] == 1
    assert len(out) == 1


def test_webmotors_curl_cffi_import_error_fallbacks_to_browser(monkeypatch):
    monkeypatch.setattr("app.scrapers.webmotors._fetch_webmotors_html_curl_cffi", lambda *_a, **_k: (_ for _ in ()).throw(ImportError("missing")))
    called = {"browser": 0}
    monkeypatch.setattr("app.scrapers.webmotors.fetch_html_browser", lambda url, *, ctx, **kwargs: (called.__setitem__("browser", called["browser"] + 1) or SimpleNamespace(html=HTML_WITH_ITEM, final_url=url)))
    out = scrape_webmotors("https://www.webmotors.com.br/carros/estoque", ScrapeContext(source="webmotors", extra={"webmotors_curl_cffi_enabled": True}))
    assert called["browser"] == 1
    assert len(out) == 1


def test_webmotors_curl_cffi_challenge_fallbacks_to_browser(monkeypatch):
    challenge = "<html><body>Access to this page has been denied provider=perimeterx</body></html>"
    monkeypatch.setattr("app.scrapers.webmotors._fetch_webmotors_html_curl_cffi", lambda *_a, **_k: (200, challenge))
    called = {"browser": 0}
    monkeypatch.setattr("app.scrapers.webmotors.fetch_html_browser", lambda url, *, ctx, **kwargs: (called.__setitem__("browser", called["browser"] + 1) or SimpleNamespace(html=HTML_WITH_ITEM, final_url=url)))
    out = scrape_webmotors("https://www.webmotors.com.br/carros/estoque", ScrapeContext(source="webmotors", extra={"webmotors_curl_cffi_enabled": True}))
    assert called["browser"] == 1
    assert len(out) == 1


def test_webmotors_curl_cffi_no_items_ambiguous_fallbacks_to_browser(monkeypatch):
    monkeypatch.setattr("app.scrapers.webmotors._fetch_webmotors_html_curl_cffi", lambda *_a, **_k: (200, "<html><body>layout mudou</body></html>"))
    called = {"browser": 0}
    monkeypatch.setattr("app.scrapers.webmotors.fetch_html_browser", lambda url, *, ctx, **kwargs: (called.__setitem__("browser", called["browser"] + 1) or SimpleNamespace(html=HTML_WITH_ITEM, final_url=url)))
    out = scrape_webmotors("https://www.webmotors.com.br/carros/estoque", ScrapeContext(source="webmotors", extra={"webmotors_curl_cffi_enabled": True}))
    assert called["browser"] == 1
    assert len(out) == 1


def test_webmotors_curl_cffi_impersonate_default_and_custom():
    from app.scrapers.webmotors import _extra_str

    assert _extra_str(ScrapeContext(source="webmotors", extra={}), "webmotors_curl_cffi_impersonate", "chrome") == "chrome"
    assert (
        _extra_str(
            ScrapeContext(source="webmotors", extra={"webmotors_curl_cffi_impersonate": "safari"}),
            "webmotors_curl_cffi_impersonate",
            "chrome",
        )
        == "safari"
    )


def test_webmotors_curl_cffi_challenge_then_browser_block_keeps_curl_diag(monkeypatch):
    challenge = "<html><body>Access to this page has been denied provider=perimeterx</body></html>"
    blocked_html = "<html><head><title>Just a moment...</title></head><body>checking your browser</body></html>"
    monkeypatch.setattr("app.scrapers.webmotors._fetch_webmotors_html_curl_cffi", lambda *_a, **_k: (200, challenge))
    monkeypatch.setattr("app.scrapers.webmotors.fetch_html_browser", lambda url, *, ctx, **kwargs: SimpleNamespace(html=blocked_html, final_url=url))

    with pytest.raises(RuntimeError) as exc:
        scrape_webmotors(
            "https://www.webmotors.com.br/carros/estoque",
            ScrapeContext(source="webmotors", extra={"webmotors_curl_cffi_enabled": True}),
        )

    reason = str(exc.value)
    assert "WM_DIAG::" in reason
    assert "curl_cffi_fallback_reason=challenge" in reason
