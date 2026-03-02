from __future__ import annotations

import logging
import random
import re
import string
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.settings import settings
from app.integrations.facebook.constants import (
    LOGIN_URL,
    MARKETPLACE_URL,
    PAIRING_CODE_PREFIX,
    PAIRING_CODE_SIZE,
    PAIRING_TTL_MINUTES,
    STATUS_ACTIVE,
    STATUS_BLOCKED,
    STATUS_CHALLENGE_REQUIRED,
    STATUS_EXPIRED,
    STATUS_DISABLED,
    STATUS_PENDING_AUTH,
)
from app.integrations.facebook.guards import fb_user_lock
from app.integrations.facebook.playwright_manager import fb_playwright_manager
from app.integrations.facebook.storage import ensure_profile_dir
from app.integrations.facebook.types import PairingValidation
from app.integrations.facebook.validator import fb_validate_session
from app.models.fb_session import FBSession

logger = logging.getLogger(__name__)

PAIRING_CODE_RE = re.compile(r"^FB-[A-Z0-9]{4}$")
ALLOWED_STATUS_TRANSITIONS = {
    STATUS_PENDING_AUTH: {STATUS_ACTIVE, STATUS_CHALLENGE_REQUIRED, STATUS_EXPIRED, STATUS_BLOCKED},
    STATUS_ACTIVE: {STATUS_ACTIVE, STATUS_CHALLENGE_REQUIRED, STATUS_EXPIRED, STATUS_BLOCKED, STATUS_DISABLED},
    STATUS_DISABLED: set(),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def generate_pairing_code() -> str:
    chars = "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(PAIRING_CODE_SIZE))
    return f"{PAIRING_CODE_PREFIX}-{chars}"


def normalize_pairing_code(code: str) -> str:
    return (code or "").strip().upper()


def is_valid_pairing_code(code: str) -> bool:
    return bool(PAIRING_CODE_RE.match(normalize_pairing_code(code)))


def action_hint_for_status(status: str) -> str:
    if status == STATUS_ACTIVE:
        return "OK"
    if status == STATUS_PENDING_AUTH:
        return "Finalize no link"
    if status in {STATUS_EXPIRED, STATUS_CHALLENGE_REQUIRED, STATUS_BLOCKED}:
        return "Reautenticar via /fb connect"
    if status == STATUS_DISABLED:
        return "Sessão desabilitada; use /fb connect"
    return "Reautenticar via /fb connect"


def can_transition_status(current: str, target: str) -> bool:
    if target == STATUS_PENDING_AUTH:
        return False
    return target in ALLOWED_STATUS_TRANSITIONS.get(current, set())


def get_or_create_session(db: Session, user_id: str) -> FBSession:
    sess = db.query(FBSession).filter(FBSession.user_id == user_id).one_or_none()
    if sess:
        if not sess.profile_dir:
            sess.profile_dir = str(ensure_profile_dir(user_id))
        return sess
    profile_dir = str(ensure_profile_dir(user_id))
    sess = FBSession(user_id=user_id, profile_dir=profile_dir, status=STATUS_PENDING_AUTH)
    db.add(sess)
    return sess


def issue_pairing_code(db: Session, user_id: str) -> FBSession:
    sess = get_or_create_session(db, user_id)
    sess.pairing_code = generate_pairing_code()
    sess.pairing_expires_at = _now() + timedelta(minutes=PAIRING_TTL_MINUTES)
    sess.pairing_used_at = None
    sess.status = STATUS_PENDING_AUTH
    db.commit()
    db.refresh(sess)
    logger.info("fb_pairing_issued", extra={"correlation_id": sess.pairing_code, "user_id": user_id})
    return sess


def pairing_link(pairing_code: str) -> str:
    base = (settings.public_base_url or "").rstrip("/")
    if not base:
        return f"/auth/facebook?code={pairing_code}"
    return f"{base}/auth/facebook?code={pairing_code}"


def validate_pairing_code(db: Session, code: str, consume: bool = False) -> tuple[PairingValidation, FBSession | None]:
    normalized = normalize_pairing_code(code)
    if not is_valid_pairing_code(normalized):
        return PairingValidation(ok=False, reason="invalid_code_format"), None
    now = _now()
    sess = db.query(FBSession).filter(func.lower(FBSession.pairing_code) == normalized.lower()).one_or_none()
    if not sess:
        return PairingValidation(ok=False, reason="code_not_found"), None
    if sess.status == STATUS_DISABLED:
        return PairingValidation(ok=False, reason="disabled"), sess
    exp = sess.pairing_expires_at
    if exp is not None and exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if not exp or exp < now:
        sess.status = "EXPIRED"
        db.commit()
        return PairingValidation(ok=False, reason="code_expired"), sess
    if sess.pairing_used_at is not None:
        return PairingValidation(ok=False, reason="code_already_used"), sess
    if consume:
        sess.pairing_used_at = now
        db.commit()
        db.refresh(sess)
    return PairingValidation(ok=True), sess


async def start_onboarding(user_id: str, profile_dir: str, correlation_id: str) -> None:
    logger.info("fb_onboarding_start", extra={"correlation_id": correlation_id, "user_id": user_id})
    async with fb_playwright_manager.open_context(user_id=user_id, profile_dir=ensure_profile_dir(user_id), headless=False, correlation_id=correlation_id) as context:
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=45000)
        await page.goto(MARKETPLACE_URL, wait_until="domcontentloaded", timeout=45000)


async def complete_onboarding(db: Session, code: str) -> FBSession | None:
    check, sess = validate_pairing_code(db, code, consume=True)
    if not check.ok or not sess:
        return None
    result = await fb_validate_session(sess.user_id, sess.profile_dir, correlation_id=code)
    if not can_transition_status(sess.status, result.status):
        sess.last_error_kind = "INVALID_TRANSITION"
        sess.last_error_message = f"{sess.status}->{result.status}"[:256]
        db.commit()
        return None
    sess.last_check_at = result.checked_at
    sess.session_validated_at = result.checked_at
    sess.last_error_kind = result.error_kind
    sess.last_error_message = (result.error_message or "")[:256] or None
    sess.status = result.status
    if result.status == STATUS_ACTIVE:
        sess.last_ok_at = result.checked_at
    db.commit()
    db.refresh(sess)
    logger.info("fb_onboarding_complete", extra={"correlation_id": code, "user_id": sess.user_id, "status": sess.status})
    return sess


async def validate_user_session(db: Session, sess: FBSession, correlation_id: str) -> FBSession | None:
    async with fb_user_lock.acquire(sess.user_id) as acquired:
        if not acquired:
            return None
        result = await fb_validate_session(sess.user_id, sess.profile_dir, correlation_id=correlation_id)
        if can_transition_status(sess.status, result.status):
            sess.status = result.status
        sess.last_check_at = result.checked_at
        sess.last_error_kind = result.error_kind
        sess.last_error_message = (result.error_message or "")[:256] or None
        if result.status == STATUS_ACTIVE:
            sess.last_ok_at = result.checked_at
        db.commit()
        db.refresh(sess)
        return sess


def disconnect_session(db: Session, user_id: str) -> FBSession | None:
    sess = db.query(FBSession).filter(FBSession.user_id == user_id).one_or_none()
    if not sess:
        return None
    sess.status = STATUS_DISABLED
    db.commit()
    db.refresh(sess)
    return sess
