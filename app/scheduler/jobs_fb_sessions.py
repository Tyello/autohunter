from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.db.session import SessionLocal
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
            .filter(FBSession.status == "ACTIVE")
            .order_by(FBSession.last_check_at.asc().nullsfirst())
            .limit(25)
            .all()
        )
        for sess in sessions:
            result = await fb_validate_session(sess.user_id, sess.profile_dir, correlation_id=str(sess.id))
            sess.status = result.status
            sess.last_check_at = now
            sess.last_error_kind = result.error_kind
            sess.last_error_message = (result.error_message or "")[:256] or None
            if result.status == "ACTIVE":
                sess.last_ok_at = now
        db.commit()
    finally:
        db.close()
