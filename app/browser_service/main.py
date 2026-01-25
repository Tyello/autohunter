from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

from app.core.settings import settings
from app.services.playwright_pool import get_playwright_pool


app = FastAPI(title="AutoHunter Browser Service", version="0.1.0")


class FetchReq(BaseModel):
    url: str
    source: str = "unknown"
    proxy_server: Optional[str] = None
    timeout_ms: int = 30000
    wait_until: str = "networkidle"
    min_delay_ms: int = 250
    max_delay_ms: int = 900


class FetchResp(BaseModel):
    html: str
    final_url: str


class FetchJsonReq(BaseModel):
    url: str
    source: str = "unknown"
    proxy_server: Optional[str] = None
    timeout_ms: int = 30000
    wait_until: str = "domcontentloaded"
    capture_mode: str = "any_json"
    min_delay_ms: int = 250
    max_delay_ms: int = 900


class FetchJsonResp(BaseModel):
    data: dict
    final_url: str
    data_url: str


def _check_token(req: Request) -> None:
    token = getattr(settings, "playwright_service_token", None)
    if not token:
        return
    got = req.headers.get("X-Playwright-Token") or ""
    if got != token:
        raise HTTPException(status_code=401, detail="unauthorized")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/v1/stats")
def stats(req: Request):
    _check_token(req)
    pool = get_playwright_pool()
    return pool.stats()


@app.post("/v1/fetch", response_model=FetchResp)
def fetch(req: Request, body: FetchReq):
    _check_token(req)
    try:
        pool = get_playwright_pool()
        r = pool.fetch(
            body.url,
            source=body.source,
            proxy_server=body.proxy_server,
            timeout_ms=body.timeout_ms,
            wait_until=body.wait_until,
            min_delay_ms=body.min_delay_ms,
            max_delay_ms=body.max_delay_ms,
        )
        return FetchResp(html=r.html, final_url=r.final_url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/v1/fetch_json", response_model=FetchJsonResp)
def fetch_json(req: Request, body: FetchJsonReq):
    _check_token(req)
    try:
        pool = get_playwright_pool()
        r = pool.fetch_json(
            body.url,
            source=body.source,
            proxy_server=body.proxy_server,
            timeout_ms=body.timeout_ms,
            wait_until=body.wait_until,
            capture_mode=body.capture_mode,
            min_delay_ms=body.min_delay_ms,
            max_delay_ms=body.max_delay_ms,
        )
        return FetchJsonResp(data=r.data, final_url=r.final_url, data_url=r.data_url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
