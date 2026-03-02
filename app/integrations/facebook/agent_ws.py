from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import logging
from fastapi import WebSocket, WebSocketDisconnect

from app.db.session import SessionLocal
from app.integrations.facebook.agent_service import consume_bootstrap_token, update_agent_result
from app.integrations.facebook.constants import STATUS_AGENT_ONLINE
from app.integrations.facebook.guards import action_hint_for_status
from app.models.fb_agent_session import FBAgentSession
from app.web.routes_fb_agent import manager

logger = logging.getLogger(__name__)


async def handle_fb_agent_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    hello = await websocket.receive_json()
    token = hello.get("token")
    if not token:
        await websocket.close(code=4401)
        return

    with SessionLocal() as db:
        sess = consume_bootstrap_token(db, token)
        if not sess:
            await websocket.close(code=4401)
            return
        sess.agent_id = ((hello.get("agent_id") or "")[:64] or None)
        sess.agent_version = ((hello.get("agent_version") or "")[:32] or None)
        sess.last_seen_at = datetime.now(timezone.utc)
        sess.status = STATUS_AGENT_ONLINE
        sess.action_hint = action_hint_for_status(sess.status)
        db.commit()
        db.refresh(sess)
        user_id = sess.user_id

    await manager.connect(user_id, websocket)
    await manager.send_task(user_id, {"type": "validate_session", "task_id": f"init-{int(datetime.now().timestamp())}"})

    async def _ping_loop() -> None:
        while True:
            await asyncio.sleep(30)
            await websocket.send_json({"type": "ping"})

    ping_task = asyncio.create_task(_ping_loop())
    try:
        while True:
            msg = await websocket.receive_json()
            if msg.get("type") == "pong":
                with SessionLocal() as db:
                    row = db.query(FBAgentSession).filter(FBAgentSession.user_id == user_id).one_or_none()
                    if row:
                        row.last_seen_at = datetime.now(timezone.utc)
                        db.commit()
                continue

            if msg.get("task_id"):
                with SessionLocal() as db:
                    update_agent_result(
                        db,
                        user_id=user_id,
                        status=msg.get("status") or STATUS_AGENT_ONLINE,
                        error_kind=msg.get("error_kind"),
                        reason=msg.get("reason"),
                    )
                await websocket.send_json({"type": "ack", "task_id": msg["task_id"]})
    except WebSocketDisconnect:
        pass
    finally:
        ping_task.cancel()
        await manager.disconnect(user_id, websocket)
