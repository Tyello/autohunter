from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.orm import Session

from app.core.settings import settings
from app.models.user import User
from app.services.app_kv_service import get_kv, set_kv
from app.services.http_session import get_shared_session
from app.services.premium_subscription_service import activate_manual_premium

logger = logging.getLogger(__name__)

MERCADOPAGO_API_BASE = "https://api.mercadopago.com"
_KV_KEY_PREFIX = "mercadopago_webhook_payment"


class InvalidSignatureError(Exception):
    pass


def build_checkout_url_with_reference(url: str, chat_id: int, plan_period: str) -> str:
    """Anexa external_reference='{chat_id}:{plan_period}' a um link de checkout do Mercado Pago."""
    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query))
    query["external_reference"] = f"{chat_id}:{plan_period}"
    return urlunsplit(parsed._replace(query=urlencode(query)))


def parse_external_reference(value: str | None) -> tuple[int, str] | None:
    if not value or ":" not in value:
        return None
    chat_id_str, plan_period = value.split(":", 1)
    try:
        chat_id = int(chat_id_str)
    except ValueError:
        return None
    plan_period = plan_period.strip().lower()
    if plan_period not in ("monthly", "annual"):
        return None
    return chat_id, plan_period


def verify_webhook_signature(
    x_signature: str | None,
    x_request_id: str | None,
    data_id: str,
    secret: str,
) -> bool:
    """Valida o header x-signature conforme o algoritmo manual do Mercado Pago.

    Manifest: "id:{data.id};request-id:{x-request-id};ts:{ts};" assinado com
    HMAC-SHA256 usando o webhook secret; comparado ao valor v1 do header.
    Ref: https://www.mercadopago.com.br/developers/en/docs/your-integrations/notifications/webhooks
    """
    if not x_signature:
        return False

    parts: dict[str, str] = {}
    for chunk in x_signature.split(","):
        if "=" not in chunk:
            continue
        key, value = chunk.split("=", 1)
        parts[key.strip()] = value.strip()

    ts = parts.get("ts")
    v1 = parts.get("v1")
    if not ts or not v1:
        return False

    manifest = f"id:{data_id.lower()};request-id:{x_request_id or ''};ts:{ts};"
    computed = hmac.new(secret.encode("utf-8"), manifest.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, v1)


def fetch_payment(payment_id: str) -> dict:
    access_token = settings.mercadopago_access_token
    if not access_token:
        raise RuntimeError("MERCADOPAGO_ACCESS_TOKEN nao configurado")

    session = get_shared_session("mercadopago")
    response = session.get(
        f"{MERCADOPAGO_API_BASE}/v1/payments/{payment_id}",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


@dataclass
class ProcessResult:
    ok: bool
    payment_id: str
    payment_status: str | None
    duplicate: bool
    activated: bool
    reason: str | None = None


def process_payment_notification(db: Session, payment_id: str) -> ProcessResult:
    kv_key = f"{_KV_KEY_PREFIX}:{payment_id}"
    existing = get_kv(db, kv_key)
    if existing:
        return ProcessResult(
            ok=True,
            payment_id=payment_id,
            payment_status=existing.get("status"),
            duplicate=True,
            activated=False,
            reason="already_processed",
        )

    payment = fetch_payment(payment_id)
    status = payment.get("status")
    external_reference = payment.get("external_reference")

    activated = False
    reason: str | None = None

    if status == "approved":
        parsed = parse_external_reference(external_reference)
        if not parsed:
            reason = "invalid_external_reference"
        else:
            chat_id, plan_period = parsed
            user = db.query(User).filter(User.telegram_chat_id == chat_id).first()
            if not user:
                reason = "user_not_found"
            else:
                result = activate_manual_premium(
                    db,
                    user_id=user.id,
                    period=plan_period,
                    activated_by="mercadopago_webhook",
                    source="mercadopago_webhook",
                )
                activated = result.ok
                if not result.ok:
                    reason = "activation_failed"
    else:
        reason = f"payment_status_{status}"

    set_kv(
        db,
        kv_key,
        {
            "status": status,
            "activated": activated,
            "reason": reason,
            "processed_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    return ProcessResult(
        ok=True,
        payment_id=payment_id,
        payment_status=status,
        duplicate=False,
        activated=activated,
        reason=reason,
    )
