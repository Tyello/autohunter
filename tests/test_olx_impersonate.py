"""OLX: o User-Agent precisa ser coerente com a versao do Chrome impersonada pelo curl_cffi
(antes era fixo em Chrome/122 com TLS chrome120), e o default acompanha uma versao recente."""

import pytest

from app.core.settings import Settings
from app.scrapers import olx


@pytest.mark.parametrize(
    "impersonate, major",
    [("chrome136", "136"), ("chrome120", "120"), ("chrome131_android", "131"), ("", "122"), ("safari18_0", "122")],
)
def test_user_agent_follows_impersonated_chrome_version(impersonate, major):
    ua = olx._olx_user_agent(impersonate)
    assert f"Chrome/{major}.0.0.0" in ua
    assert ua.startswith("Mozilla/5.0 ")


def test_module_user_agent_matches_configured_impersonation():
    assert olx._OLX_USER_AGENT == olx._olx_user_agent(olx._OLX_IMPERSONATE)


def test_default_impersonate_is_recent_chrome():
    assert Settings.model_fields["olx_impersonate"].default == "chrome136"


def test_olx_requests_use_the_shared_user_agent(monkeypatch):
    seen = []

    class _Resp:
        status_code = 200
        text = "<html></html>"
        headers = {}

    def _fake_get(url, **kw):
        seen.append(kw["headers"]["User-Agent"])
        return _Resp()

    monkeypatch.setattr(olx.cf_requests, "get", _fake_get)
    monkeypatch.setattr(olx, "_load_playwright_cookies_for_olx", lambda ctx: {})
    from app.sources.types import ScrapeContext

    ctx = ScrapeContext(source="olx")
    for fn, arg in ((olx._fetch_olx_detail_html, "https://www.olx.com.br/d/x"),):
        try:
            fn(arg, ctx)
        except Exception:
            pass
    try:
        olx._fetch_http_hybrid("https://www.olx.com.br/autos?q=x", ctx, min_delay_ms=0, max_delay_ms=0)
    except Exception:
        pass
    assert seen and all(ua == olx._OLX_USER_AGENT for ua in seen)
