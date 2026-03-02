from __future__ import annotations

import asyncio

import logging
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.db.deps import get_db
from app.integrations.facebook.agent_service import issue_bootstrap_token
from app.integrations.facebook.guards import normalize_pairing_code
from app.integrations.facebook.ratelimit import TTLRateLimiter

logger = logging.getLogger(__name__)
router = APIRouter(tags=["facebook-agent"])
_rate_bootstrap_ip = TTLRateLimiter(max_hits=20, ttl_seconds=60)
_rate_bootstrap_code = TTLRateLimiter(max_hits=5, ttl_seconds=300)
_rate_bootstrap_user = TTLRateLimiter(max_hits=8, ttl_seconds=300)


class AgentConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}
        self._lock = asyncio.Lock()

    async def connect(self, user_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            old = self._connections.get(user_id)
            self._connections[user_id] = websocket
        if old and old is not websocket:
            await old.close(code=4001, reason="replaced_by_new_connection")

    async def disconnect(self, user_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            current = self._connections.get(user_id)
            if current is websocket:
                self._connections.pop(user_id, None)

    async def send_task(self, user_id: str, payload: dict) -> bool:
        ws = self._connections.get(user_id)
        if not ws:
            return False
        await ws.send_json(payload)
        return True


manager = AgentConnectionManager()


def _client_ip(request: Request) -> str:
    c = request.client
    return c.host if c else "unknown"


@router.get("/auth/facebook", response_class=HTMLResponse)
async def auth_facebook_page(code: str):
    normalized = normalize_pairing_code(code)
    html = f"""
    <html><head><meta charset='utf-8'><title>AutoHunter Facebook Agent</title></head>
    <body style="font-family: sans-serif; max-width: 760px; margin: 2rem auto;">
      <h2>Facebook Marketplace (Bring-your-own-browser)</h2>
      <p>Código de pareamento: <strong>{normalized}</strong></p>
      <p>Instale/rode o agent local no seu computador e faça login no navegador local.</p>
      <p>Sem cookies: o servidor recebe apenas status/resultados.</p>
      <button onclick="copyCmd()">Copiar comando do agent</button>
      <pre id="cmd">python -m fb_agent --code {normalized} --server window.location.origin</pre>
      <script>
        function copyCmd() {{
          const cmd = `python -m fb_agent --code {normalized} --server ${{window.location.origin}}`;
          navigator.clipboard.writeText(cmd);
          document.getElementById('cmd').textContent = cmd + '\n(copiado)';
        }}
      </script>
    </body></html>
    """
    return HTMLResponse(content=html)


@router.get("/auth/facebook/agent/bootstrap")
async def fb_agent_bootstrap(code: str, request: Request, db: Session = Depends(get_db)):
    normalized = normalize_pairing_code(code)
    ip = _client_ip(request)
    if not await _rate_bootstrap_ip.hit(f"ip:{ip}"):
        raise HTTPException(status_code=429, detail="rate_limited_ip")
    if not await _rate_bootstrap_code.hit(f"code:{normalized}"):
        raise HTTPException(status_code=429, detail="rate_limited_code")

    token, sess, err = issue_bootstrap_token(db, normalized)
    if err or not token or not sess:
        raise HTTPException(status_code=400, detail=err or "bootstrap_failed")
    if not await _rate_bootstrap_user.hit(f"user:{sess.user_id}"):
        raise HTTPException(status_code=429, detail="rate_limited_user")

    logger.info("fb_agent_bootstrap", extra={"correlation_id": normalized, "user_id": sess.user_id, "ip": ip})
    ws_scheme = "wss" if request.url.scheme == "https" else "ws"
    ws_url = str(request.url.replace(scheme=ws_scheme, path="/ws/fb/agent", query=""))
    return {
        "ok": True,
        "ws_url": ws_url,
        "ws_path": "/ws/fb/agent",
        "token": token,
        "user_id": sess.user_id,
        "expires_at": sess.bootstrap_token_expires_at.isoformat(),
    }
