from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.settings import settings
from app.db.deps import get_db
from app.services.mercadopago_webhook_service import (
    process_payment_notification,
    verify_webhook_signature,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["mercadopago-webhook"])


@router.post("/webhooks/mercadopago")
async def mercadopago_webhook(request: Request, db: Session = Depends(get_db)):
    try:
        body = await request.json()
    except ValueError:
        body = {}

    notification_type = body.get("type") or request.query_params.get("type")
    data_id = (
        (body.get("data") or {}).get("id")
        or request.query_params.get("data.id")
        or request.query_params.get("id")
    )

    if notification_type != "payment" or not data_id:
        return {"ok": True, "ignored": True}

    data_id = str(data_id)

    secret = settings.mercadopago_webhook_secret
    if not secret:
        logger.error("mercadopago_webhook_secret_not_configured")
        raise HTTPException(status_code=503, detail="webhook_not_configured")

    x_signature = request.headers.get("x-signature")
    x_request_id = request.headers.get("x-request-id")
    if not verify_webhook_signature(x_signature, x_request_id, data_id, secret):
        logger.warning("mercadopago_webhook_invalid_signature", extra={"payment_id": data_id})
        raise HTTPException(status_code=401, detail="invalid_signature")

    result = process_payment_notification(db, data_id)
    logger.info(
        "mercadopago_webhook_processed",
        extra={
            "payment_id": result.payment_id,
            "payment_status": result.payment_status,
            "duplicate": result.duplicate,
            "activated": result.activated,
            "reason": result.reason,
        },
    )
    return {"ok": True}
