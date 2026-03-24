from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.deps import get_db
from app.integrations.facebook.guards import UserOperationBusyError, normalize_pairing_code
from app.integrations.facebook.ratelimit import TTLRateLimiter
from app.integrations.facebook.service import complete_onboarding, start_onboarding, validate_pairing_code

logger = logging.getLogger(__name__)

router = APIRouter(tags=["facebook-auth"])
_rate_ip_by_endpoint = TTLRateLimiter(max_hits=10, ttl_seconds=60)
_rate_code_start = TTLRateLimiter(max_hits=3, ttl_seconds=300)
_rate_code_complete = TTLRateLimiter(max_hits=5, ttl_seconds=300)


class FBCodePayload(BaseModel):
    code: str


# Legacy path kept for backward compatibility with older onboarding links.
# Prefer the newer fb-agent bootstrap flow for new operational setups.
@router.get("/auth/facebook/legacy", response_class=HTMLResponse)
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


async def _limited_response(request: Request, code: str, endpoint: str, reason: str) -> None:
    ip = _client_ip(request)
    logger.warning(
        "fb_onboarding_rate_limited",
        extra={
            "correlation_id": code,
            "ip": ip,
            "code": code,
            "endpoint": endpoint,
            "limited": True,
            "reason": reason,
        },
    )
    raise HTTPException(
        status_code=429,
        detail={"error": "rate_limited", "reason": reason, "endpoint": endpoint, "retry": "try_later"},
    )


async def _apply_rate_limit(request: Request, code: str, endpoint: str) -> None:
    ip = _client_ip(request)
    if not await _rate_ip_by_endpoint.hit(f"ip:{ip}:{endpoint}"):
        await _limited_response(request, code, endpoint, "ip_per_endpoint")

    if endpoint.endswith("/start") and not await _rate_code_start.hit(f"start:{code}"):
        await _limited_response(request, code, endpoint, "code_start")
    if endpoint.endswith("/complete") and not await _rate_code_complete.hit(f"complete:{code}"):
        await _limited_response(request, code, endpoint, "code_complete")


@router.post("/auth/facebook/start")
async def auth_facebook_start(payload: FBCodePayload, request: Request, db: Session = Depends(get_db)):
    code = normalize_pairing_code(payload.code)
    await _apply_rate_limit(request, code, "/auth/facebook/start")
    check, sess = validate_pairing_code(db, code, consume=True)
    if not check.ok or not sess:
        raise HTTPException(status_code=400, detail=check.reason or "invalid_code")
    try:
        logger.info("fb_web_start", extra={"correlation_id": code, "user_id": sess.user_id, "ip": _client_ip(request), "code": code})
        await start_onboarding(sess.user_id, sess.profile_dir, correlation_id=code)
    except UserOperationBusyError:
        raise HTTPException(status_code=409, detail="busy_try_again")
    return {"ok": True, "status": sess.status, "correlation_id": code}


@router.post("/auth/facebook/complete")
async def auth_facebook_complete(payload: FBCodePayload, request: Request, db: Session = Depends(get_db)):
    code = normalize_pairing_code(payload.code)
    await _apply_rate_limit(request, code, "/auth/facebook/complete")
    try:
        sess = await complete_onboarding(db, code)
    except UserOperationBusyError:
        raise HTTPException(status_code=409, detail="busy_try_again")
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
    normalized = normalize_pairing_code(code)
    await _apply_rate_limit(request, normalized, "/auth/facebook/status")
    check, sess = validate_pairing_code(db, normalized, consume=False)
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
