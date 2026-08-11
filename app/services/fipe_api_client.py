from __future__ import annotations

import time
from typing import Any

import requests

from app.core.settings import settings
from app.services.fipe_rate_limiter import FipeRateLimiter


class FipeApiError(Exception):
    pass


class FipeApiClient:
    BASE_URL = "https://veiculos.fipe.org.br/api/veiculos"
    VEHICLE_TYPE_CAR = 1

    def __init__(
        self,
        *,
        rate_limit_ms: int | None = None,
        max_throttle_ms: int | None = None,
        max_retries: int | None = None,
        timeout_s: int | None = None,
        rate_limiter: FipeRateLimiter | None = None,
    ) -> None:
        self._rate_limit_ms = int(rate_limit_ms if rate_limit_ms is not None else settings.fipe_api_rate_limit_ms)
        self._max_throttle_ms = int(max_throttle_ms if max_throttle_ms is not None else settings.fipe_api_max_throttle_ms)
        self._max_retries = int(max_retries if max_retries is not None else settings.fipe_api_max_retries)
        self._timeout_s = int(timeout_s if timeout_s is not None else settings.fipe_api_timeout_s)
        self._rate_limiter = rate_limiter or FipeRateLimiter(
            rate_limit_ms=self._rate_limit_ms,
            max_throttle_ms=self._max_throttle_ms,
            recovery_after_successes=settings.fipe_throttle_recovery_after_successes,
        )
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://veiculos.fipe.org.br/",
                "Origin": "https://veiculos.fipe.org.br",
                "X-Requested-With": "XMLHttpRequest",
            }
        )

    def get_reference_tables(self) -> list[dict]:
        return self._request("ConsultarTabelaDeReferencia", {})

    def get_latest_reference_table(self) -> dict:
        tables = self.get_reference_tables()
        if not tables:
            raise FipeApiError("nenhuma tabela de referencia retornada pela API FIPE")
        return tables[0]

    def get_brands(self, reference_code: int) -> list[dict]:
        return self._request(
            "ConsultarMarcas",
            {"codigoTabelaReferencia": reference_code, "codigoTipoVeiculo": self.VEHICLE_TYPE_CAR},
        )

    def get_models(self, reference_code: int, brand_code: str) -> list[dict]:
        data = self._request(
            "ConsultarModelos",
            {
                "codigoTabelaReferencia": reference_code,
                "codigoTipoVeiculo": self.VEHICLE_TYPE_CAR,
                "codigoMarca": brand_code,
            },
        )
        if isinstance(data, dict):
            return data.get("Modelos") or []
        return data

    def get_model_years(self, reference_code: int, brand_code: str, model_code: str) -> list[dict]:
        return self._request(
            "ConsultarAnoModelo",
            {
                "codigoTabelaReferencia": reference_code,
                "codigoTipoVeiculo": self.VEHICLE_TYPE_CAR,
                "codigoMarca": brand_code,
                "codigoModelo": model_code,
            },
        )

    def get_price(
        self,
        *,
        reference_code: int,
        brand_code: str,
        model_code: str,
        model_year: int,
        fuel_code: str,
    ) -> dict:
        return self._request(
            "ConsultarValorComTodosParametros",
            {
                "codigoTabelaReferencia": reference_code,
                "codigoTipoVeiculo": self.VEHICLE_TYPE_CAR,
                "codigoMarca": brand_code,
                "codigoModelo": model_code,
                "anoModelo": model_year,
                "codigoTipoCombustivel": fuel_code,
                "tipoVeiculo": self.VEHICLE_TYPE_CAR,
                "tipoConsulta": "tradicional",
            },
        )

    def _request(self, endpoint: str, body: dict, *, attempt: int = 0) -> Any:
        self._rate_limiter.acquire()

        try:
            response = self._session.post(f"{self.BASE_URL}/{endpoint}", json=body, timeout=self._timeout_s)
        except requests.RequestException as exc:
            if attempt < self._max_retries:
                time.sleep((1000 * (2**attempt)) / 1000)
                return self._request(endpoint, body, attempt=attempt + 1)
            raise FipeApiError(f"erro de rede ao chamar {endpoint}: {exc}") from exc

        if response.status_code == 429:
            self._rate_limiter.on_429()
            retry_after = response.headers.get("Retry-After")
            wait_s = float(retry_after) if retry_after else (5000 * (2**attempt)) / 1000
            if attempt < self._max_retries:
                time.sleep(wait_s)
                return self._request(endpoint, body, attempt=attempt + 1)
            time.sleep(wait_s)
            raise FipeApiError(f"429 esgotou retries ao chamar {endpoint}")

        if not response.ok:
            if attempt < self._max_retries:
                time.sleep((1000 * (2**attempt)) / 1000)
                return self._request(endpoint, body, attempt=attempt + 1)
            raise FipeApiError(f"HTTP {response.status_code} ao chamar {endpoint}: {response.text}")

        data = response.json()
        if isinstance(data, dict) and "erro" in data:
            raise FipeApiError(str(data["erro"]))

        self._rate_limiter.on_success()
        return data
