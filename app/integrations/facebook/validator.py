from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.integrations.facebook.constants import (
    ERROR_BLOCKED,
    ERROR_CHECKPOINT,
    ERROR_LOGIN_WALL,
    ERROR_NET,
    ERROR_UNKNOWN,
    MARKETPLACE_URL,
    STATUS_ACTIVE,
    STATUS_BLOCKED,
    STATUS_CHALLENGE_REQUIRED,
    STATUS_EXPIRED,
)
from app.integrations.facebook.guards import fb_user_operation_lock
from app.integrations.facebook.playwright_manager import fb_playwright_manager
from app.integrations.facebook.storage import ensure_debug_dir, ensure_profile_dir, rotate_debug_files
from app.integrations.facebook.types import FBValidationResult

logger = logging.getLogger(__name__)


def classify_marketplace_state(*, final_url: str, html: str) -> FBValidationResult:
    url = (final_url or "").lower()
    body = (html or "").lower()

    if "checkpoint" in url or "checkpoint" in body:
        return FBValidationResult(status=STATUS_CHALLENGE_REQUIRED, error_kind=ERROR_CHECKPOINT, error_message="checkpoint detected")
    if any(t in body for t in ["suspicious activity", "access denied", "temporarily blocked", "unusual activity"]):
        return FBValidationResult(status=STATUS_BLOCKED, error_kind=ERROR_BLOCKED, error_message="blocked signals detected")
    if ("/login" in url) or any(t in body for t in ["log in", "entrar", "faça login"]):
        return FBValidationResult(status=STATUS_EXPIRED, error_kind=ERROR_LOGIN_WALL, error_message="login wall detected")
    if "marketplace" in url or "marketplace" in body:
        return FBValidationResult(status=STATUS_ACTIVE)
    return FBValidationResult(status=STATUS_EXPIRED, error_kind=ERROR_UNKNOWN, error_message="marketplace not visible")


async def fb_validate_session(user_id: str, profile_dir: str, correlation_id: str, acquire_lock: bool = True) -> FBValidationResult:
    now = datetime.now(timezone.utc)
    profile = ensure_profile_dir(user_id)
    logger.info("fb_validate_start", extra={"correlation_id": correlation_id, "user_id": user_id})
    page = None
    try:
        lock_ctx = fb_user_operation_lock(user_id) if acquire_lock else None
        if lock_ctx:
            await lock_ctx.__aenter__()
        try:
            async with fb_playwright_manager.open_context(user_id=user_id, profile_dir=profile, headless=True, correlation_id=correlation_id) as context:
                page = context.pages[0] if context.pages else await context.new_page()
                await page.goto(MARKETPLACE_URL, wait_until="domcontentloaded", timeout=45000)
                await page.wait_for_timeout(1500)
                html = await page.content()
                result = classify_marketplace_state(final_url=page.url, html=html)
                result.checked_at = now
                if result.status != STATUS_ACTIVE:
                    debug = ensure_debug_dir(user_id)
                    stem = now.strftime("%Y%m%d_%H%M%S")
                    await page.screenshot(path=str(debug / f"{stem}.png"), full_page=True)
                    (debug / f"{stem}.html").write_text(html, encoding="utf-8")
                    rotate_debug_files(user_id, max_files=20)
                logger.info("fb_validate_done", extra={"correlation_id": correlation_id, "user_id": user_id, "status": result.status})
                return result
        finally:
            if lock_ctx:
                await lock_ctx.__aexit__(None, None, None)
    except Exception as exc:
        msg = str(exc)[:256]
        kind = ERROR_NET if any(k in msg.lower() for k in ["timeout", "net", "connection", "dns"]) else ERROR_UNKNOWN
        debug = ensure_debug_dir(user_id)
        stem = now.strftime("%Y%m%d_%H%M%S")
        if page is not None:
            try:
                await page.screenshot(path=str(debug / f"{stem}.png"), full_page=True)
            except Exception:
                logger.exception("fb_validate_debug_screenshot_failed", extra={"correlation_id": correlation_id, "user_id": user_id})
        (debug / f"{stem}.html").write_text(f"validator_exception={msg}", encoding="utf-8")
        rotate_debug_files(user_id, max_files=20)
        return FBValidationResult(status=STATUS_EXPIRED, error_kind=kind, error_message=msg, checked_at=now)
