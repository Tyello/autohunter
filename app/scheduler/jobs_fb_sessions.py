from __future__ import annotations

import asyncio
from app.db.session import SessionLocal
from app.integrations.facebook.service import validate_user_session
from app.models.fb_session import FBSession


def job_fb_sessions_healthcheck() -> None:
    asyncio.run(_job_fb_sessions_healthcheck_async())


async def _job_fb_sessions_healthcheck_async() -> None:
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
            await validate_user_session(db, sess, correlation_id=str(sess.id))
    finally:
        db.close()
