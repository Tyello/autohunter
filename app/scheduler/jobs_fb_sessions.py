from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.db.session import SessionLocal
from app.integrations.facebook.constants import STATUS_AGENT_ONLINE
from app.integrations.facebook.guards import action_hint_for_status
from app.models.fb_agent_session import FBAgentSession
from app.web.routes_fb_agent import manager

logger = logging.getLogger(__name__)


def job_fb_sessions_healthcheck() -> None:
    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(hours=24)
    db = SessionLocal()
    try:
        sessions = db.query(FBAgentSession).all()
        for sess in sessions:
            if sess.last_seen_at and sess.last_seen_at < stale_cutoff and sess.status == STATUS_AGENT_ONLINE:
                sess.action_hint = "abrir agent novamente"
            elif not sess.last_seen_at:
                sess.action_hint = "use /fb connect"

            if sess.status == STATUS_AGENT_ONLINE:
                try:
                    sent = _push_validate_task(sess.user_id)
                    if not sent:
                        sess.action_hint = "abrir agent novamente"
                except Exception:
                    logger.exception("fb_agent_push_validate_failed", extra={"user_id": sess.user_id})

        db.commit()
    finally:
        db.close()


def _push_validate_task(user_id: str) -> bool:
    import asyncio

    payload = {"type": "validate_session", "task_id": f"sched-{int(datetime.now().timestamp())}"}
    return asyncio.run(manager.send_task(user_id, payload))
