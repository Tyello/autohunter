from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import logging
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.integrations.facebook.constants import PAIRING_TTL_MINUTES, STATUS_ACTIVE, STATUS_AGENT_ONLINE, STATUS_DISABLED, STATUS_PENDING_AGENT
from app.integrations.facebook.guards import action_hint_for_status, can_transition_status, is_expired, normalize_pairing_code, validate_pairing_code_format
from app.integrations.facebook.service import generate_pairing_code
from app.integrations.facebook.types import PairingValidation
from app.models.fb_agent_session import FBAgentSession

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_or_create_agent_session(db: Session, user_id: str) -> FBAgentSession:
    sess = db.query(FBAgentSession).filter(FBAgentSession.user_id == user_id).one_or_none()
    if sess:
        return sess
    sess = FBAgentSession(user_id=user_id, status=STATUS_PENDING_AGENT, action_hint=action_hint_for_status(STATUS_PENDING_AGENT))
    db.add(sess)
    return sess


def issue_agent_pairing_code(db: Session, user_id: str) -> FBAgentSession:
    sess = get_or_create_agent_session(db, user_id)
    sess.pairing_code = generate_pairing_code()
    sess.pairing_expires_at = _now() + timedelta(minutes=PAIRING_TTL_MINUTES)
    sess.pairing_used_at = None
    sess.status = STATUS_PENDING_AGENT
    sess.action_hint = action_hint_for_status(sess.status)
    db.commit()
    db.refresh(sess)
    logger.info("fb_agent_pairing_issued", extra={"correlation_id": sess.pairing_code, "user_id": user_id})
    return sess


def validate_agent_pairing_code(db: Session, code: str, consume: bool = False) -> tuple[PairingValidation, FBAgentSession | None]:
    normalized = normalize_pairing_code(code)
    if not validate_pairing_code_format(normalized):
        return PairingValidation(ok=False, reason="code_invalid_format"), None

    now = _now()
    sess = db.query(FBAgentSession).filter(func.lower(FBAgentSession.pairing_code) == normalized.lower()).one_or_none()
    if not sess:
        return PairingValidation(ok=False, reason="code_not_found"), None
    if sess.status == STATUS_DISABLED:
        return PairingValidation(ok=False, reason="disabled"), sess
    if is_expired(sess.pairing_expires_at, now=now):
        if can_transition_status(sess.status, "EXPIRED"):
            sess.status = "EXPIRED"
            sess.action_hint = action_hint_for_status(sess.status)
        db.commit()
        return PairingValidation(ok=False, reason="code_expired"), sess
    if sess.pairing_used_at is not None:
        return PairingValidation(ok=False, reason="code_already_used"), sess
    if consume:
        sess.pairing_used_at = now
        db.commit()
        db.refresh(sess)
    return PairingValidation(ok=True), sess


def issue_bootstrap_token(db: Session, code: str) -> tuple[str | None, FBAgentSession | None, str | None]:
    check, sess = validate_agent_pairing_code(db, code, consume=True)
    if not check.ok or not sess:
        return None, sess, check.reason
    sess.bootstrap_token = secrets.token_urlsafe(32)
    sess.bootstrap_token_expires_at = _now() + timedelta(minutes=5)
    sess.bootstrap_token_used_at = None
    db.commit()
    db.refresh(sess)
    logger.info("fb_agent_bootstrap_issued", extra={"correlation_id": code, "user_id": sess.user_id})
    return sess.bootstrap_token, sess, None


def consume_bootstrap_token(db: Session, token: str) -> FBAgentSession | None:
    now = _now()
    sess = db.query(FBAgentSession).filter(FBAgentSession.bootstrap_token == token).one_or_none()
    if not sess or sess.bootstrap_token_used_at is not None or is_expired(sess.bootstrap_token_expires_at, now=now):
        return None
    sess.bootstrap_token_used_at = now
    sess.status = STATUS_AGENT_ONLINE
    sess.last_seen_at = now
    sess.action_hint = action_hint_for_status(sess.status)
    db.commit()
    db.refresh(sess)
    return sess


def update_agent_result(db: Session, user_id: str, status: str, error_kind: str | None, reason: str | None) -> FBAgentSession | None:
    now = _now()
    sess = db.query(FBAgentSession).filter(FBAgentSession.user_id == user_id).one_or_none()
    if not sess:
        return None
    sess.last_seen_at = now
    sess.last_check_at = now
    if can_transition_status(sess.status, status):
        sess.status = status
    sess.last_error_kind = error_kind
    sess.last_error_message = (reason or None)[:256] if reason else None
    if status == STATUS_ACTIVE:
        sess.last_ok_at = now
    sess.action_hint = action_hint_for_status(sess.status)
    db.commit()
    db.refresh(sess)
    return sess


def disconnect_agent_session(db: Session, user_id: str) -> FBAgentSession | None:
    sess = db.query(FBAgentSession).filter(FBAgentSession.user_id == user_id).one_or_none()
    if not sess:
        return None
    sess.status = STATUS_DISABLED
    sess.bootstrap_token = None
    sess.bootstrap_token_expires_at = None
    sess.action_hint = action_hint_for_status(sess.status)
    db.commit()
    db.refresh(sess)
    return sess
