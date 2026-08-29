from __future__ import annotations

import pytest

from app.services.fipe_api_client import FipeApiClient, FipeApiError
from app.services.fipe_rate_limiter import FipeRateLimiter


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


def test_catalog_ttl_cache_avoids_repeated_external_calls_in_bootstrap_scenario(monkeypatch):
    """Cenário de bootstrap: várias resoluções de marca/modelo/ano para a MESMA
    marca+modelo (comum quando várias wishlists on-demand caem na mesma janela de
    batch). Com o client compartilhado, a 2a+ chamada deve vir do cache TTL em vez
    de bater na API externa de novo — reduzindo chamadas externas."""
    client = _client(monkeypatch)
    calls = {"n": 0}

    def fake_request(endpoint, body):
        calls["n"] += 1
        if endpoint == "ConsultarTabelaDeReferencia":
            return [{"Codigo": 320, "Mes": "agosto/2026"}]
        if endpoint == "ConsultarMarcas":
            return [{"Label": "Honda", "Value": "22"}]
        if endpoint == "ConsultarModelos":
            return [{"Label": "Civic", "Value": "9"}]
        if endpoint == "ConsultarAnoModelo":
            return [{"Label": "2019 Gasolina", "Value": "2019-1"}]
        raise AssertionError(f"endpoint inesperado: {endpoint}")

    monkeypatch.setattr(client, "_request", fake_request)

    # Simula 5 lookups on-demand na mesma marca/modelo dentro do mesmo batch.
    for _ in range(5):
        ref = client.get_latest_reference_table()
        brands = client.get_brands(ref["Codigo"])
        models = client.get_models(ref["Codigo"], brands[0]["Value"])
        client.get_model_years(ref["Codigo"], brands[0]["Value"], models[0]["Value"])

    # 4 endpoints distintos batidos apenas na 1a iteração; as 4 seguintes vêm do cache.
    assert calls["n"] == 4

    stats = client.cache_stats()
    assert stats["misses"] == 4
    assert stats["hits"] == 4 * 4  # 4 chamadas cacheadas x 4 iterações restantes


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


class _SpyRateLimiter:
    def __init__(self):
        self.acquire_calls = 0
        self.success_calls = 0
        self.on_429_calls = 0

    def acquire(self):
        self.acquire_calls += 1

    def on_success(self):
        self.success_calls += 1

    def on_429(self):
        self.on_429_calls += 1


def test_shared_rate_limiter_used_when_provided(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_a, **_k: None)
    spy = _SpyRateLimiter()
    client = FipeApiClient(rate_limit_ms=0, max_throttle_ms=5000, max_retries=3, timeout_s=20, rate_limiter=spy)

    def fake_post(url, json, timeout):
        return _FakeResponse(status_code=200, json_body={"ok": True})

    monkeypatch.setattr(client._session, "post", fake_post)

    client._request("ConsultarMarcas", {})

    assert spy.acquire_calls == 1
    assert spy.success_calls == 1
    assert spy.on_429_calls == 0
    assert client._rate_limiter is spy


def test_default_rate_limiter_created_when_none(monkeypatch):
    client = _client(monkeypatch)
    assert isinstance(client._rate_limiter, FipeRateLimiter)
