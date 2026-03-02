from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.db.session import SessionLocal
from app.integrations.facebook.constants import ERROR_UNKNOWN, STATUS_ACTIVE
from app.integrations.facebook.guards import UserOperationBusyError, can_transition_status, fb_user_operation_lock
from app.integrations.facebook.validator import fb_validate_session
from app.models.fb_session import FBSession


def job_fb_sessions_healthcheck() -> None:
    asyncio.run(_job_fb_sessions_healthcheck_async())


async def _job_fb_sessions_healthcheck_async() -> None:
    now = datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        sessions = (
            db.query(FBSession)
            .filter(FBSession.status == STATUS_ACTIVE)
            .order_by(FBSession.last_check_at.asc().nullsfirst())
            .limit(25)
            .all()
        )
        for sess in sessions:
            try:
                async with fb_user_operation_lock(sess.user_id):
                    result = await fb_validate_session(sess.user_id, sess.profile_dir, correlation_id=str(sess.id))
            except UserOperationBusyError:
                continue
            sess.last_check_at = now
            is_error = result.status != STATUS_ACTIVE
            sess.last_error_kind = result.error_kind or (ERROR_UNKNOWN if is_error else None)
            sess.last_error_message = (result.error_message or ("validation_failed" if is_error else ""))[:256] or None
            if can_transition_status(sess.status, result.status):
                sess.status = result.status
            if result.status == STATUS_ACTIVE:
                sess.last_ok_at = now
        db.commit()
    finally:
        db.close()
