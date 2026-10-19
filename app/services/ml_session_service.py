"""Sessao logada do Mercado Livre (storage_state) + rastreio de saude.

Sem sessao, o ML manda o trafego do Pi para `account-verification`. Com a sessao de uma
conta (idealmente uma conta de servico da Garagem Alvo) a busca volta normal. Este modulo:

- le os cookies do storage_state da source `mercadolivre`;
- descreve a sessao (logada? quando expira?) sem expor valores;
- registra o resultado de cada uso em `AppKV` (`ml_session_health`) e emite eventos de
  telemetria quando a sessao e rejeitada/recuperada, para ficar claro se esta funcionando.

Troca de conta = substituir o arquivo do storage_state (ver `scripts/ml_session.py`).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import app.scrapers.hybrid_cookies as hybrid_cookies
from app.services.storage_state_cookies import storage_state_path

logger = logging.getLogger(__name__)

SOURCE = "mercadolivre"
HEALTH_KV_KEY = "ml_session_health"

# Cookies que existem so com login (sem eles o ML trata como anonimo).
AUTH_COOKIE_NAMES = ("orguserid", "ssid")

OUTCOME_OK = "ok"  # sessao presente e a pagina veio normal
OUTCOME_REJECTED = "rejected"  # sessao presente, mas o ML mandou captcha/verificacao
OUTCOME_NO_SESSION = "no_session"  # sem sessao e o ML mandou captcha/verificacao

# Reescreve o KV no maximo a cada N s enquanto o resultado nao muda.
_WRITE_THROTTLE_S = 600

_last_write_at: float = 0.0


def _is_ml_domain(cookie: dict) -> bool:
    return "mercadoli" in str(cookie.get("domain", ""))


def session_cookies(proxy: Optional[str] = None) -> Dict[str, str]:
    cookies = hybrid_cookies._load_storage_state_cookies(source=SOURCE, proxy_server=proxy)
    return {
        str(c["name"]): str(c["value"])
        for c in cookies
        if _is_ml_domain(c) and c.get("name") and c.get("value") is not None
    }


def session_info(proxy: Optional[str] = None, *, now: Optional[float] = None) -> Dict[str, Any]:
    """Resumo da sessao salva (sem valores de cookie)."""
    now = time.time() if now is None else now
    cookies = [
        c for c in hybrid_cookies._load_storage_state_cookies(source=SOURCE, proxy_server=proxy) if _is_ml_domain(c)
    ]
    auth = [c for c in cookies if c.get("name") in AUTH_COOKIE_NAMES and c.get("value")]
    # expires <= 0 (-1) = cookie de sessao do navegador, sem data.
    expiries = [float(c["expires"]) for c in auth if float(c.get("expires") or 0) > 0]
    earliest = min(expiries) if expiries else None

    path = storage_state_path(source=SOURCE, proxy_server=proxy)
    try:
        file_age_h = round((now - path.stat().st_mtime) / 3600, 1)
    except OSError:
        file_age_h = None

    return {
        "present": bool(cookies),
        "logged_in": {c["name"] for c in auth} >= set(AUTH_COOKIE_NAMES),
        "cookie_count": len(cookies),
        "auth_cookies_expire_at": (
            datetime.fromtimestamp(earliest, tz=timezone.utc).isoformat() if earliest else None
        ),
        "auth_cookies_expired": bool(earliest and earliest < now),
        "file_age_hours": file_age_h,
    }


def classify_outcome(*, has_session: bool, blocked: bool) -> Optional[str]:
    if has_session:
        return OUTCOME_REJECTED if blocked else OUTCOME_OK
    return OUTCOME_NO_SESSION if blocked else None


def next_state(
    prev: Optional[Dict[str, Any]],
    outcome: str,
    *,
    now_iso: str,
    url: Optional[str] = None,
) -> Tuple[Dict[str, Any], Optional[str]]:
    """Novo estado do KV e o evento de transicao (ou None)."""
    prev = dict(prev or {})
    prev_outcome = prev.get("last_outcome")
    state = {
        "last_outcome": outcome,
        "last_outcome_at": now_iso,
        "ok_count": int(prev.get("ok_count") or 0),
        "rejected_count": int(prev.get("rejected_count") or 0),
        "last_ok_at": prev.get("last_ok_at"),
        "last_rejected_at": prev.get("last_rejected_at"),
        "last_rejected_url": prev.get("last_rejected_url"),
    }
    if outcome == OUTCOME_OK:
        state["ok_count"] += 1
        state["last_ok_at"] = now_iso
    elif outcome == OUTCOME_REJECTED:
        state["rejected_count"] += 1
        state["last_rejected_at"] = now_iso
        state["last_rejected_url"] = url

    event = None
    if outcome == OUTCOME_REJECTED and prev_outcome != OUTCOME_REJECTED:
        event = "ml_session_rejected"
    elif outcome == OUTCOME_OK and prev_outcome == OUTCOME_REJECTED:
        event = "ml_session_recovered"
    return state, event


def record_outcome(outcome: Optional[str], *, proxy: Optional[str] = None, url: Optional[str] = None) -> None:
    """Persiste o resultado (best effort: nunca derruba o scrape)."""
    global _last_write_at
    if not outcome:
        return
    try:
        from app.db.session import session_scope
        from app.services.app_kv_service import get_kv, set_kv
        from app.services.telemetry_events_service import emit_event

        with session_scope() as db:
            prev = get_kv(db, HEALTH_KV_KEY)
            now_iso = datetime.now(timezone.utc).isoformat()
            state, event = next_state(prev, outcome, now_iso=now_iso, url=url)
            changed = (prev or {}).get("last_outcome") != outcome
            if not (changed or event or time.time() - _last_write_at >= _WRITE_THROTTLE_S):
                return
            state["session"] = session_info(proxy)
            set_kv(db, HEALTH_KV_KEY, state)
            _last_write_at = time.time()
            if event:
                ok = event == "ml_session_recovered"
                emit_event(
                    db,
                    level="info" if ok else "warn",
                    event_type=event,
                    source=SOURCE,
                    message=event,
                    evidence={"url": url, "session": state["session"]},
                    tags=["ml_session"],
                )
                db.commit()
    except Exception:
        logger.debug("ml_session: falha ao registrar resultado", exc_info=True)
