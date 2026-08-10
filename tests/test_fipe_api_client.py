from __future__ import annotations

import pytest

from app.services.fipe_api_client import FipeApiClient, FipeApiError


class _FakeResponse:
    def __init__(self, *, status_code=200, json_body=None, headers=None, text=""):
        self.status_code = status_code
        self._json_body = json_body if json_body is not None else {}
        self.headers = headers or {}
        self.text = text

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    def json(self):
        return self._json_body


def _client(monkeypatch, **kwargs):
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)
    return FipeApiClient(rate_limit_ms=0, max_throttle_ms=5000, max_retries=3, timeout_s=20, **kwargs)


def test_get_latest_reference_table(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr(
        client,
        "_request",
        lambda endpoint, body: [{"Codigo": 320, "Mes": "agosto/2026"}, {"Codigo": 319, "Mes": "julho/2026"}],
    )

    result = client.get_latest_reference_table()

    assert result == {"Codigo": 320, "Mes": "agosto/2026"}


def test_get_latest_reference_table_empty_raises(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr(client, "_request", lambda endpoint, body: [])

    with pytest.raises(FipeApiError):
        client.get_latest_reference_table()


def test_429_backoff(monkeypatch):
    client = _client(monkeypatch)
    calls = []
    sleeps = []
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))

    def fake_post(url, json, timeout):
        calls.append(1)
        if len(calls) == 1:
            return _FakeResponse(status_code=429, headers={"Retry-After": "2"})
        return _FakeResponse(status_code=200, json_body={"ok": True})

    monkeypatch.setattr(client._session, "post", fake_post)

    result = client._request("ConsultarMarcas", {})

    assert result == {"ok": True}
    assert len(calls) == 2
    assert sleeps[0] == pytest.approx(2.0)


def test_429_exhausts_retries_raises(monkeypatch):
    client = _client(monkeypatch)
    calls = []

    def fake_post(url, json, timeout):
        calls.append(1)
        return _FakeResponse(status_code=429, headers={})

    monkeypatch.setattr(client._session, "post", fake_post)

    with pytest.raises(FipeApiError):
        client._request("ConsultarMarcas", {})

    assert len(calls) == client._max_retries + 1


def test_fipe_error_response_raises(monkeypatch):
    client = _client(monkeypatch)
    calls = []

    def fake_post(url, json, timeout):
        calls.append(1)
        return _FakeResponse(status_code=200, json_body={"erro": "Parametros invalidos"})

    monkeypatch.setattr(client._session, "post", fake_post)

    with pytest.raises(FipeApiError, match="Parametros invalidos"):
        client._request("ConsultarMarcas", {})

    assert len(calls) == 1


def test_timeout_passed_to_requests(monkeypatch):
    client = _client(monkeypatch)
    captured = {}

    def fake_post(url, json, timeout):
        captured["timeout"] = timeout
        return _FakeResponse(status_code=200, json_body={"ok": True})

    monkeypatch.setattr(client._session, "post", fake_post)

    client._request("ConsultarMarcas", {})

    assert captured["timeout"] == 20
