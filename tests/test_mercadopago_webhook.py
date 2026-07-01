import hashlib
import hmac
import uuid

import pytest

from app.core.settings import settings
from app.models.account import Account
from app.models.plan import Plan
from app.models.subscription import Subscription
from app.models.user import User
from app.services import mercadopago_webhook_service as svc


def _mk_account_with_user(db, chat_id):
    acc = Account(id=uuid.uuid4(), type="personal", name="acc", is_active=True)
    user = User(id=uuid.uuid4(), telegram_chat_id=chat_id, username=f"u{chat_id}", is_active=True, account_id=acc.id)
    db.add(acc)
    db.add(user)
    db.commit()
    return acc, user


def _mk_premium_plan(db):
    plan = Plan(code="premium", name="Premium", daily_alert_limit=10, max_wishlists=5, is_active=True)
    db.add(plan)
    db.commit()
    return plan


def _sign(secret: str, data_id: str, request_id: str, ts: str) -> str:
    manifest = f"id:{data_id.lower()};request-id:{request_id};ts:{ts};"
    digest = hmac.new(secret.encode("utf-8"), manifest.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"ts={ts},v1={digest}"


def test_verify_webhook_signature_valid():
    secret = "topsecret"
    header = _sign(secret, "123456", "req-1", "1700000000")
    assert svc.verify_webhook_signature(header, "req-1", "123456", secret) is True


def test_verify_webhook_signature_invalid_when_tampered():
    secret = "topsecret"
    header = _sign(secret, "123456", "req-1", "1700000000")
    assert svc.verify_webhook_signature(header, "req-1", "999999", secret) is False


def test_verify_webhook_signature_missing_header():
    assert svc.verify_webhook_signature(None, "req-1", "123456", "topsecret") is False


def test_parse_external_reference_valid():
    assert svc.parse_external_reference("555:monthly") == (555, "monthly")


def test_parse_external_reference_invalid_period():
    assert svc.parse_external_reference("555:weekly") is None


def test_parse_external_reference_malformed():
    assert svc.parse_external_reference("not-a-reference") is None


def test_process_payment_notification_activates_premium_on_approved(db, monkeypatch):
    _mk_premium_plan(db)
    _, user = _mk_account_with_user(db, 555)

    monkeypatch.setattr(
        svc,
        "fetch_payment",
        lambda payment_id: {"status": "approved", "external_reference": "555:monthly"},
    )

    result = svc.process_payment_notification(db, "pay-1")

    assert result.activated is True
    assert result.duplicate is False
    sub = db.query(Subscription).filter(Subscription.account_id == user.account_id).first()
    assert sub is not None
    assert sub.status == "active"


def test_process_payment_notification_ignores_pending_payment(db, monkeypatch):
    _mk_premium_plan(db)
    _mk_account_with_user(db, 556)

    monkeypatch.setattr(
        svc,
        "fetch_payment",
        lambda payment_id: {"status": "pending", "external_reference": "556:monthly"},
    )

    result = svc.process_payment_notification(db, "pay-2")

    assert result.activated is False
    assert result.payment_status == "pending"
    assert db.query(Subscription).count() == 0


def test_process_payment_notification_ignores_rejected_payment(db, monkeypatch):
    _mk_premium_plan(db)
    _mk_account_with_user(db, 557)

    monkeypatch.setattr(
        svc,
        "fetch_payment",
        lambda payment_id: {"status": "rejected", "external_reference": "557:monthly"},
    )

    result = svc.process_payment_notification(db, "pay-3")

    assert result.activated is False
    assert db.query(Subscription).count() == 0


def test_process_payment_notification_is_idempotent(db, monkeypatch):
    _mk_premium_plan(db)
    _mk_account_with_user(db, 558)

    calls = {"count": 0}

    def _fake_fetch(payment_id):
        calls["count"] += 1
        return {"status": "approved", "external_reference": "558:monthly"}

    monkeypatch.setattr(svc, "fetch_payment", _fake_fetch)

    first = svc.process_payment_notification(db, "pay-4")
    second = svc.process_payment_notification(db, "pay-4")

    assert first.duplicate is False
    assert second.duplicate is True
    assert calls["count"] == 1
    assert db.query(Subscription).count() == 1


def test_webhook_route_rejects_invalid_signature(client, monkeypatch):
    monkeypatch.setattr(settings, "mercadopago_webhook_secret", "topsecret")
    monkeypatch.setattr(settings, "mercadopago_access_token", "test-token")

    response = client.post(
        "/webhooks/mercadopago?data.id=123456&type=payment",
        json={"type": "payment", "data": {"id": "123456"}},
        headers={"x-signature": "ts=1700000000,v1=deadbeef", "x-request-id": "req-1"},
    )

    assert response.status_code == 401


def test_webhook_route_rejects_when_secret_not_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "mercadopago_webhook_secret", None)

    response = client.post(
        "/webhooks/mercadopago?data.id=123456&type=payment",
        json={"type": "payment", "data": {"id": "123456"}},
    )

    assert response.status_code == 503


def test_webhook_route_activates_premium_on_valid_signature(db, client, monkeypatch):
    _mk_premium_plan(db)
    _, user = _mk_account_with_user(db, 559)

    secret = "topsecret"
    monkeypatch.setattr(settings, "mercadopago_webhook_secret", secret)
    monkeypatch.setattr(settings, "mercadopago_access_token", "test-token")
    monkeypatch.setattr(
        svc,
        "fetch_payment",
        lambda payment_id: {"status": "approved", "external_reference": "559:annual"},
    )

    header = _sign(secret, "999999", "req-9", "1700000001")
    response = client.post(
        "/webhooks/mercadopago?data.id=999999&type=payment",
        json={"type": "payment", "data": {"id": "999999"}},
        headers={"x-signature": header, "x-request-id": "req-9"},
    )

    assert response.status_code == 200
    sub = db.query(Subscription).filter(Subscription.account_id == user.account_id).first()
    assert sub is not None
    assert sub.status == "active"
