from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.deps import get_db
from app.integrations.facebook.guards import fb_user_lock
from app.integrations.facebook.ratelimit import TTLRateLimiter
from app.integrations.facebook.service import complete_onboarding, normalize_pairing_code, start_onboarding, validate_pairing_code

logger = logging.getLogger(__name__)


router = APIRouter(tags=["facebook-auth"])
_rate_ip = TTLRateLimiter(max_hits=10, ttl_seconds=60)
_rate_start_code = TTLRateLimiter(max_hits=3, ttl_seconds=300)
_rate_complete_code = TTLRateLimiter(max_hits=5, ttl_seconds=300)


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


async def _apply_rate_limit(request: Request, endpoint: str, code: str) -> None:
    ip = _client_ip(request)
    normalized = normalize_pairing_code(code)
    if not await _rate_ip.hit(f"ip:{ip}:{endpoint}"):
        logger.warning("fb_onboarding_rate_limited", extra={"correlation_id": normalized, "ip": ip, "code": normalized, "endpoint": endpoint, "limited": True})
        raise HTTPException(status_code=429, detail={"error": "rate_limited_ip", "endpoint": endpoint})
    if endpoint == "start":
        ok = await _rate_start_code.hit(f"code:{normalized}")
    elif endpoint == "complete":
        ok = await _rate_complete_code.hit(f"code:{normalized}")
    else:
        ok = True
    if not ok:
        logger.warning("fb_onboarding_rate_limited", extra={"correlation_id": normalized, "ip": ip, "code": normalized, "endpoint": endpoint, "limited": True})
        raise HTTPException(status_code=429, detail={"error": "rate_limited_code", "endpoint": endpoint})


@router.post("/auth/facebook/start")
async def auth_facebook_start(payload: FBCodePayload, request: Request, db: Session = Depends(get_db)):
    await _apply_rate_limit(request, "start", payload.code)
    check, sess = validate_pairing_code(db, payload.code, consume=False)
    if not check.ok or not sess:
        raise HTTPException(status_code=400, detail=check.reason or "invalid_code")
    async with fb_user_lock.acquire(sess.user_id) as acquired:
        if not acquired:
            return {"ok": False, "error": "busy_try_again"}
        logger.info("fb_web_start", extra={"correlation_id": payload.code, "user_id": sess.user_id})
        await start_onboarding(sess.user_id, sess.profile_dir, correlation_id=payload.code)
    return {"ok": True, "status": sess.status, "correlation_id": normalize_pairing_code(payload.code)}


@router.post("/auth/facebook/complete")
async def auth_facebook_complete(payload: FBCodePayload, request: Request, db: Session = Depends(get_db)):
    await _apply_rate_limit(request, "complete", payload.code)
    check, sess = validate_pairing_code(db, payload.code, consume=False)
    if not check.ok or not sess:
        raise HTTPException(status_code=400, detail=check.reason or "invalid_or_expired_code")
    async with fb_user_lock.acquire(sess.user_id) as acquired:
        if not acquired:
            return {"ok": False, "error": "busy_try_again"}
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
    await _apply_rate_limit(request, "status", code)
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
