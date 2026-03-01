from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.deps import get_db
from app.integrations.facebook.service import complete_onboarding, start_onboarding, validate_pairing_code

logger = logging.getLogger(__name__)


class _RateLimiter:
    def __init__(self, max_hits: int = 10, ttl_seconds: int = 60) -> None:
        self.max_hits = max_hits
        self.ttl_seconds = ttl_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def hit(self, key: str) -> bool:
        now = time.time()
        async with self._lock:
            q = self._events[key]
            while q and (now - q[0]) > self.ttl_seconds:
                q.popleft()
            if len(q) >= self.max_hits:
                return False
            q.append(now)
            return True


router = APIRouter(tags=["facebook-auth"])
_rate_ip = _RateLimiter(max_hits=20, ttl_seconds=60)
_rate_code = _RateLimiter(max_hits=8, ttl_seconds=60)


class FBCodePayload(BaseModel):
    code: str


@router.get("/auth/facebook", response_class=HTMLResponse)
async def auth_facebook_page(code: str):
    html = f"""
    <html><head><meta charset='utf-8'><title>AutoHunter Facebook</title></head>
    <body style="font-family: sans-serif; max-width: 720px; margin: 2rem auto;">
      <h2>Facebook Marketplace Onboarding</h2>
      <p>Código de pareamento: <strong>{code}</strong></p>
      <p>⚠️ Não envie cookies no Telegram. Faça login apenas aqui.</p>
      <button onclick="start()">Iniciar login</button>
      <button onclick="complete()">Validar sessão</button>
      <pre id="out"></pre>
      <script>
        async function start() {{
          const res = await fetch('/auth/facebook/start', {{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{code:'{code}'}})}});
          document.getElementById('out').textContent = await res.text();
        }}
        async function complete() {{
          const res = await fetch('/auth/facebook/complete', {{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{code:'{code}'}})}});
          document.getElementById('out').textContent = await res.text();
        }}
      </script>
    </body></html>
    """
    return HTMLResponse(content=html)


def _client_ip(request: Request) -> str:
    c = request.client
    return c.host if c else "unknown"


async def _apply_rate_limit(request: Request, code: str) -> None:
    ip = _client_ip(request)
    if not await _rate_ip.hit(f"ip:{ip}"):
        raise HTTPException(status_code=429, detail="rate_limited_ip")
    if not await _rate_code.hit(f"code:{code.lower()}"):
        raise HTTPException(status_code=429, detail="rate_limited_code")


@router.post("/auth/facebook/start")
async def auth_facebook_start(payload: FBCodePayload, request: Request, db: Session = Depends(get_db)):
    await _apply_rate_limit(request, payload.code)
    check, sess = validate_pairing_code(db, payload.code, consume=True)
    if not check.ok or not sess:
        raise HTTPException(status_code=400, detail=check.reason or "invalid_code")
    logger.info("fb_web_start", extra={"correlation_id": payload.code, "user_id": sess.user_id})
    await start_onboarding(sess.user_id, sess.profile_dir, correlation_id=payload.code)
    return {"ok": True, "status": sess.status, "correlation_id": payload.code}


@router.post("/auth/facebook/complete")
async def auth_facebook_complete(payload: FBCodePayload, request: Request, db: Session = Depends(get_db)):
    await _apply_rate_limit(request, payload.code)
    sess = await complete_onboarding(db, payload.code)
    if not sess:
        raise HTTPException(status_code=400, detail="invalid_or_expired_code")
    return {
        "ok": True,
        "status": sess.status,
        "last_check_at": sess.last_check_at.isoformat() if sess.last_check_at else None,
        "last_error_kind": sess.last_error_kind,
        "last_error_message": sess.last_error_message,
    }


@router.get("/auth/facebook/status")
async def auth_facebook_status(code: str, request: Request, db: Session = Depends(get_db)):
    await _apply_rate_limit(request, code)
    check, sess = validate_pairing_code(db, code, consume=False)
    if not sess:
        raise HTTPException(status_code=404, detail=check.reason or "not_found")
    return {
        "ok": check.ok,
        "status": sess.status,
        "pairing_expires_at": sess.pairing_expires_at.isoformat() if sess.pairing_expires_at else None,
        "session_validated_at": sess.session_validated_at.isoformat() if sess.session_validated_at else None,
        "last_error_kind": sess.last_error_kind,
        "last_error_message": sess.last_error_message,
    }
