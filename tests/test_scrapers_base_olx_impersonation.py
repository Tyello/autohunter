"""Regressao: o OLX passou a devolver 403 (Cloudflare "Attention Required") para
qualquer request com fingerprint TLS de Python `requests`, mesmo com o mesmo IP
residencial que recebe 200 com Chrome/curl_cffi. Prova em prod (Pi, 09/10):
requests -> 403; curl_cffi impersonate=chrome -> 200 com ~1.7MB.

fetch_response deve usar curl_cffi (impersonate) para hosts do OLX e continuar
usando requests para as demais sources."""

from types import SimpleNamespace

import pytest

from app.scrapers import base as base_mod


class _FakeCffiResponse:
    status_code = 200
    text = "<html>ok</html>"
    headers = {"Content-Type": "text/html"}

    def raise_for_status(self):
        return None


class _FakeCffiSession:
    def __init__(self):
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _FakeCffiResponse()

    def close(self):
        return None


@pytest.fixture(autouse=True)
def _clean_sessions():
    base_mod._cffi_sessions.clear()
    base_mod._cffi_sessions_created_at.clear()
    yield
    base_mod._cffi_sessions.clear()
    base_mod._cffi_sessions_created_at.clear()


def test_olx_host_uses_curl_cffi_with_impersonation(monkeypatch):
    fake = _FakeCffiSession()
    monkeypatch.setattr(base_mod, "_new_cffi_session", lambda: fake)

    def _no_requests(*a, **k):
        raise AssertionError("requests nao deve ser usado para OLX")

    monkeypatch.setattr(base_mod.requests.Session, "get", _no_requests)

    resp = base_mod.fetch_response(
        "https://www.olx.com.br/autos-e-pecas/carros-vans-e-utilitarios?q=civic",
        ctx=SimpleNamespace(source="olx"),
        headers={"User-Agent": "x", "Sec-Fetch-Mode": "navigate", "Referer": "https://www.olx.com.br/"},
        _skip_delay=True,
    )

    assert resp.text == "<html>ok</html>"
    (_, kwargs), = fake.calls
    assert kwargs["impersonate"] == base_mod._CFFI_IMPERSONATE
    # UA/Sec-* ficam por conta do impersonate (evita inconsistencia com o TLS)
    sent = {k.lower() for k in kwargs["headers"]}
    assert "user-agent" not in sent
    assert "sec-fetch-mode" not in sent
    assert "referer" in sent


def test_olx_blocked_status_still_raises_fetch_blocked(monkeypatch):
    class _Blocked(_FakeCffiResponse):
        status_code = 403
        text = "Attention Required! | Cloudflare"

    fake = _FakeCffiSession()
    fake.get = lambda url, **kw: _Blocked()
    monkeypatch.setattr(base_mod, "_new_cffi_session", lambda: fake)

    with pytest.raises(base_mod.FetchBlocked):
        base_mod.fetch_response("https://www.olx.com.br/", ctx=SimpleNamespace(source="olx"), _skip_delay=True)


def test_other_hosts_keep_using_requests(monkeypatch):
    def _no_cffi():
        raise AssertionError("curl_cffi nao deve ser usado fora do OLX")

    monkeypatch.setattr(base_mod, "_new_cffi_session", _no_cffi)

    class _Resp:
        status_code = 200
        text = "ok"
        headers = {}

        def raise_for_status(self):
            return None

    monkeypatch.setattr(base_mod.requests.Session, "get", lambda self, url, **kw: _Resp())

    resp = base_mod.fetch_response("https://www.turboclass.com.br/x", ctx=SimpleNamespace(source="turboclass"), _skip_delay=True)
    assert resp.text == "ok"


def test_falls_back_to_requests_when_curl_cffi_unavailable(monkeypatch):
    monkeypatch.setattr(base_mod, "_new_cffi_session", lambda: None)

    class _Resp:
        status_code = 200
        text = "via-requests"
        headers = {}

        def raise_for_status(self):
            return None

    monkeypatch.setattr(base_mod.requests.Session, "get", lambda self, url, **kw: _Resp())

    resp = base_mod.fetch_response("https://www.olx.com.br/", ctx=SimpleNamespace(source="olx"), _skip_delay=True)
    assert resp.text == "via-requests"
