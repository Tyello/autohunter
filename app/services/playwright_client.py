from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional, Dict, Any

import requests

from app.core.settings import settings


@dataclass
class RemoteFetchResult:
    html: str
    final_url: str


@dataclass
class RemoteJsonFetchResult:
    data: dict
    final_url: str
    data_url: str


class PlaywrightRemoteClient:
    def __init__(self, endpoint: str, token: Optional[str] = None) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.token = token
        self._s = requests.Session()

    def _headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.token:
            h["X-Playwright-Token"] = self.token
        return h

    def health(self) -> dict:
        r = self._s.get(f"{self.endpoint}/health", timeout=5)
        r.raise_for_status()
        return r.json()

    def stats(self) -> dict:
        r = self._s.get(f"{self.endpoint}/v1/stats", timeout=5, headers=self._headers())
        r.raise_for_status()
        return r.json()

    def fetch(
        self,
        url: str,
        *,
        source: str,
        proxy_server: Optional[str] = None,
        timeout_ms: int = 30000,
        wait_until: str = "networkidle",
        min_delay_ms: int = 250,
        max_delay_ms: int = 900,
    ) -> RemoteFetchResult:
        payload = {
            "url": url,
            "source": source,
            "proxy_server": proxy_server,
            "timeout_ms": timeout_ms,
            "wait_until": wait_until,
            "min_delay_ms": min_delay_ms,
            "max_delay_ms": max_delay_ms,
        }
        r = self._s.post(f"{self.endpoint}/v1/fetch", json=payload, headers=self._headers(), timeout=max(10, int(timeout_ms / 1000) + 5))
        r.raise_for_status()
        j = r.json()
        return RemoteFetchResult(html=j["html"], final_url=j["final_url"])

    def fetch_json(
        self,
        url: str,
        *,
        source: str,
        proxy_server: Optional[str] = None,
        timeout_ms: int = 30000,
        wait_until: str = "domcontentloaded",
        capture_mode: str = "any_json",
        min_delay_ms: int = 250,
        max_delay_ms: int = 900,
    ) -> RemoteJsonFetchResult:
        payload = {
            "url": url,
            "source": source,
            "proxy_server": proxy_server,
            "timeout_ms": timeout_ms,
            "wait_until": wait_until,
            "capture_mode": capture_mode,
            "min_delay_ms": min_delay_ms,
            "max_delay_ms": max_delay_ms,
        }
        r = self._s.post(f"{self.endpoint}/v1/fetch_json", json=payload, headers=self._headers(), timeout=max(10, int(timeout_ms / 1000) + 5))
        r.raise_for_status()
        j = r.json()
        return RemoteJsonFetchResult(data=j["data"], final_url=j["final_url"], data_url=j["data_url"])


_CLIENT: Optional[PlaywrightRemoteClient] = None


def get_playwright_client() -> PlaywrightRemoteClient:
    global _CLIENT
    if _CLIENT is None:
        if not settings.playwright_endpoint:
            raise RuntimeError("playwright_endpoint is not configured")
        _CLIENT = PlaywrightRemoteClient(settings.playwright_endpoint, token=settings.playwright_service_token)
    return _CLIENT
