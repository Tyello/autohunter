from app.scrapers.mercadolivre import (
    _is_ml_shell_without_results,
    _is_ml_security_or_captcha_page,
    scrape_mercadolivre,
)
from app.scrapers.base import FetchBlocked
from app.sources.types import ScrapeContext


ML_SHELL_HTML = """
<html>
  <head>
    <title>Honda Civic | Mercado Livre</title>
  </head>
  <body>
    <div id="root"></div>
  </body>
</html>
"""

ML_RESULTS_HTML = """
<html>
  <head><title>Honda Civic Si: 12 carros a partir de R$ 100,000</title></head>
  <body>
    <li class="ui-search-layout__item">
      <a class="ui-search-link" href="https://carro.mercadolivre.com.br/MLB-123456789-honda-civic-si-_JM">
        <h2 class="ui-search-item__title">Honda Civic Si 2019</h2>
      </a>
      <span class="andes-money-amount__fraction">120.000</span>
    </li>
  </body>
</html>
"""


def test_ml_shell_detector_true_for_shell_html():
    assert _is_ml_shell_without_results(ML_SHELL_HTML) is True


def test_ml_shell_detector_false_when_cards_exist():
    assert _is_ml_shell_without_results(ML_RESULTS_HTML) is False


def test_ml_shell_detector_false_for_empty_html():
    assert _is_ml_shell_without_results("") is False


def test_scrape_mercadolivre_uses_browser_networkidle_on_shell(monkeypatch):
    calls = {"browser": 0, "wait_until": None, "block_resources": None, "timeout_ms": None, "ctx": None}

    def _fake_fetch(url, ctx=None, timeout=25):
        return ML_SHELL_HTML

    class _Res:
        def __init__(self, html):
            self.html = html

    def _fake_browser_fetch(url, **kwargs):
        calls["browser"] += 1
        calls["wait_until"] = kwargs.get("wait_until")
        calls["block_resources"] = kwargs.get("block_resources")
        calls["timeout_ms"] = kwargs.get("timeout_ms")
        calls["ctx"] = kwargs.get("ctx")
        return _Res(ML_RESULTS_HTML)

    monkeypatch.setattr("app.scrapers.mercadolivre._fetch_html_ml", _fake_fetch)
    monkeypatch.setattr("app.scrapers.mercadolivre.fetch_html_browser", _fake_browser_fetch)

    monkeypatch.setattr("app.scrapers.mercadolivre.settings.enable_playwright", True)
    ctx = ScrapeContext(source="mercadolivre", browser_fallback_enabled=True)
    items = scrape_mercadolivre("https://lista.mercadolivre.com.br/veiculos/carros-caminhonetes/civic-si", ctx)

    assert calls["browser"] == 1
    assert calls["wait_until"] == "networkidle"
    assert calls["block_resources"] is False
    assert calls["timeout_ms"] == 25_000
    assert calls["ctx"] is ctx
    assert len(items) == 1


def test_scrape_mercadolivre_does_not_fallback_when_initial_has_cards(monkeypatch):
    calls = {"browser": 0}

    def _fake_fetch(url, ctx=None, timeout=25):
        return ML_RESULTS_HTML

    class _Res:
        def __init__(self, html):
            self.html = html

    def _fake_browser_fetch(url, **kwargs):
        calls["browser"] += 1
        return _Res(ML_RESULTS_HTML)

    monkeypatch.setattr("app.scrapers.mercadolivre._fetch_html_ml", _fake_fetch)
    monkeypatch.setattr("app.scrapers.mercadolivre.fetch_html_browser", _fake_browser_fetch)

    ctx = ScrapeContext(source="mercadolivre", browser_fallback_enabled=True)
    items = scrape_mercadolivre("https://lista.mercadolivre.com.br/veiculos/carros-caminhonetes/civic-si", ctx)

    assert calls["browser"] == 0
    assert len(items) == 1


def test_scrape_mercadolivre_shell_fallback_not_called_when_playwright_disabled(monkeypatch):
    calls = {"browser": 0}

    def _fake_fetch(url, ctx=None, timeout=25):
        return ML_SHELL_HTML

    def _fake_browser_fetch(url, **kwargs):
        calls["browser"] += 1
        raise AssertionError("browser should not be called")

    monkeypatch.setattr("app.scrapers.mercadolivre._fetch_html_ml", _fake_fetch)
    monkeypatch.setattr("app.scrapers.mercadolivre.fetch_html_browser", _fake_browser_fetch)
    monkeypatch.setattr("app.scrapers.mercadolivre.settings.enable_playwright", False)

    ctx = ScrapeContext(source="mercadolivre", browser_fallback_enabled=True)
    items = scrape_mercadolivre("https://lista.mercadolivre.com.br/veiculos/carros-caminhonetes/civic-si", ctx)

    assert calls["browser"] == 0
    assert items == []


def test_scrape_mercadolivre_shell_fallback_not_called_when_ctx_flag_disabled(monkeypatch):
    calls = {"browser": 0}

    def _fake_fetch(url, ctx=None, timeout=25):
        return ML_SHELL_HTML

    def _fake_browser_fetch(url, **kwargs):
        calls["browser"] += 1
        raise AssertionError("browser should not be called")

    monkeypatch.setattr("app.scrapers.mercadolivre._fetch_html_ml", _fake_fetch)
    monkeypatch.setattr("app.scrapers.mercadolivre.fetch_html_browser", _fake_browser_fetch)
    monkeypatch.setattr("app.scrapers.mercadolivre.settings.enable_playwright", True)

    ctx = ScrapeContext(source="mercadolivre", browser_fallback_enabled=False)
    items = scrape_mercadolivre("https://lista.mercadolivre.com.br/veiculos/carros-caminhonetes/civic-si", ctx)

    assert calls["browser"] == 0
    assert items == []


def test_scrape_mercadolivre_shell_fallback_not_called_without_ctx(monkeypatch):
    calls = {"browser": 0}

    def _fake_fetch(url, ctx=None, timeout=25):
        return ML_SHELL_HTML

    def _fake_browser_fetch(url, **kwargs):
        calls["browser"] += 1
        raise AssertionError("browser should not be called")

    monkeypatch.setattr("app.scrapers.mercadolivre._fetch_html_ml", _fake_fetch)
    monkeypatch.setattr("app.scrapers.mercadolivre.fetch_html_browser", _fake_browser_fetch)
    monkeypatch.setattr("app.scrapers.mercadolivre.settings.enable_playwright", True)

    items = scrape_mercadolivre("https://lista.mercadolivre.com.br/veiculos/carros-caminhonetes/civic-si", None)

    assert calls["browser"] == 0
    assert items == []


def test_scrape_mercadolivre_browser_security_page_raises_blocked(monkeypatch):
    def _fake_fetch(url, ctx=None, timeout=25):
        return ML_SHELL_HTML

    class _Res:
        def __init__(self):
            self.html = "<html><head><title>Seguridad — Mercado Libre</title></head><body></body></html>"
            self.final_url = "https://lista.mercadolivre.com.br/captcha/wall"

    def _fake_browser_fetch(url, **kwargs):
        return _Res()

    monkeypatch.setattr("app.scrapers.mercadolivre._fetch_html_ml", _fake_fetch)
    monkeypatch.setattr("app.scrapers.mercadolivre.fetch_html_browser", _fake_browser_fetch)
    monkeypatch.setattr("app.scrapers.mercadolivre.settings.enable_playwright", True)

    ctx = ScrapeContext(source="mercadolivre", browser_fallback_enabled=True)
    try:
        scrape_mercadolivre("https://lista.mercadolivre.com.br/veiculos/carros-caminhonetes/civic-si", ctx)
        assert False, "expected FetchBlocked"
    except FetchBlocked as exc:
        assert exc.reason == "ml_security_or_captcha_page"


def test_ml_security_detector_by_title_or_url():
    html = "<html><head><title>Seguridad — Mercado Libre</title></head></html>"
    assert _is_ml_security_or_captcha_page(html) is True
    assert _is_ml_security_or_captcha_page("<html></html>", "https://lista.mercadolivre.com.br/captcha/wall") is True
    assert _is_ml_security_or_captcha_page(ML_RESULTS_HTML, "https://lista.mercadolivre.com.br/veiculos") is False


def test_scrape_ml_shell_retry_with_fresh_context(monkeypatch):
    calls = {"browser": 0, "reset": 0}

    def _fake_fetch(url, ctx=None, timeout=25):
        return ML_SHELL_HTML

    class _Res:
        def __init__(self, html, final_url="https://lista.mercadolivre.com.br/veiculos"):
            self.html = html
            self.final_url = final_url

    responses = [_Res(ML_SHELL_HTML), _Res(ML_RESULTS_HTML)]

    def _fake_browser_fetch(url, **kwargs):
        calls["browser"] += 1
        return responses.pop(0)

    def _fake_reset(*args, **kwargs):
        calls["reset"] += 1

    monkeypatch.setattr("app.scrapers.mercadolivre._fetch_html_ml", _fake_fetch)
    monkeypatch.setattr("app.scrapers.mercadolivre.fetch_html_browser", _fake_browser_fetch)
    monkeypatch.setattr("app.scrapers.mercadolivre.reset_browser_state_for_source", _fake_reset)
    monkeypatch.setattr("app.scrapers.mercadolivre.settings.enable_playwright", True)

    ctx = ScrapeContext(source="mercadolivre", browser_fallback_enabled=True)
    items = scrape_mercadolivre("https://lista.mercadolivre.com.br/veiculos/carros-caminhonetes/civic-si", ctx)
    assert len(items) == 1
    assert calls["browser"] == 2
    assert calls["reset"] == 1


def test_scrape_ml_shell_retry_limited(monkeypatch):
    def _fake_fetch(url, ctx=None, timeout=25):
        return ML_SHELL_HTML

    class _Res:
        def __init__(self):
            self.html = ML_SHELL_HTML
            self.final_url = "https://lista.mercadolivre.com.br/veiculos"

    monkeypatch.setattr("app.scrapers.mercadolivre._fetch_html_ml", _fake_fetch)
    monkeypatch.setattr("app.scrapers.mercadolivre.fetch_html_browser", lambda *a, **k: _Res())
    monkeypatch.setattr("app.scrapers.mercadolivre.reset_browser_state_for_source", lambda *a, **k: None)
    monkeypatch.setattr("app.scrapers.mercadolivre.settings.enable_playwright", True)

    ctx = ScrapeContext(source="mercadolivre", browser_fallback_enabled=True)
    try:
        scrape_mercadolivre("https://lista.mercadolivre.com.br/veiculos/carros-caminhonetes/civic-si", ctx)
        assert False
    except FetchBlocked as exc:
        assert exc.reason == "ml_shell_without_results"
