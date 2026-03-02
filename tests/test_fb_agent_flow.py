from __future__ import annotations

from datetime import timedelta, timezone, datetime

from starlette.websockets import WebSocketDisconnect

from app.integrations.facebook.agent_service import issue_agent_pairing_code, issue_bootstrap_token, validate_agent_pairing_code
from app.models.fb_agent_session import FBAgentSession


def test_pairing_ttl_and_one_time(db):
    sess = issue_agent_pairing_code(db, "u-agent-1")
    ok1, _ = validate_agent_pairing_code(db, sess.pairing_code or "", consume=True)
    assert ok1.ok is True

    ok2, _ = validate_agent_pairing_code(db, sess.pairing_code or "", consume=False)
    assert ok2.ok is False
    assert ok2.reason == "code_already_used"

    row = db.query(FBAgentSession).filter(FBAgentSession.user_id == "u-agent-1").one()
    row.pairing_used_at = None
    row.pairing_expires_at = datetime.now(timezone.utc) - timedelta(minutes=11)
    db.commit()

    ok3, _ = validate_agent_pairing_code(db, sess.pairing_code or "", consume=False)
    assert ok3.ok is False
    assert ok3.reason == "code_expired"


def test_bootstrap_token_issuance_and_expiry(db):
    sess = issue_agent_pairing_code(db, "u-agent-2")
    token, row, err = issue_bootstrap_token(db, sess.pairing_code or "")
    assert err is None
    assert token
    assert row

    db_row = db.query(FBAgentSession).filter(FBAgentSession.user_id == "u-agent-2").one()
    db_row.bootstrap_token_expires_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    db.commit()

    res = db.query(FBAgentSession).filter(FBAgentSession.bootstrap_token == token).one()
    assert res.bootstrap_token_expires_at is not None


def test_websocket_handshake_validation(client, db):
    sess = issue_agent_pairing_code(db, "u-agent-ws")
    boot = client.get("/auth/facebook/agent/bootstrap", params={"code": sess.pairing_code})
    assert boot.status_code == 200
    token = boot.json()["token"]

    with client.websocket_connect("/ws/fb/agent") as ws:
        ws.send_json({"token": token, "agent_id": "a1", "agent_version": "0.1"})
        first = ws.receive_json()
        assert first["type"] == "validate_session"


def test_single_connection_per_user(client, db):
    sess = issue_agent_pairing_code(db, "u-agent-single")
    token1 = client.get("/auth/facebook/agent/bootstrap", params={"code": sess.pairing_code}).json()["token"]

    with client.websocket_connect("/ws/fb/agent") as ws1:
        ws1.send_json({"token": token1, "agent_id": "a1", "agent_version": "0.1"})
        _ = ws1.receive_json()

        sess2 = issue_agent_pairing_code(db, "u-agent-single")
        token2 = client.get("/auth/facebook/agent/bootstrap", params={"code": sess2.pairing_code}).json()["token"]
        with client.websocket_connect("/ws/fb/agent") as ws2:
            ws2.send_json({"token": token2, "agent_id": "a2", "agent_version": "0.2"})
            _ = ws2.receive_json()

        try:
            ws1.receive_json()
            assert False, "old websocket should be closed"
        except Exception:
            assert True


def test_state_transitions_on_ws_result(client, db):
    sess = issue_agent_pairing_code(db, "u-agent-state")
    token = client.get("/auth/facebook/agent/bootstrap", params={"code": sess.pairing_code}).json()["token"]

    with client.websocket_connect("/ws/fb/agent") as ws:
        ws.send_json({"token": token, "agent_id": "a1", "agent_version": "0.1"})
        task = ws.receive_json()
        ws.send_json({"task_id": task["task_id"], "ok": True, "status": "ACTIVE", "reason": None, "error_kind": None})
        ack = ws.receive_json()
        assert ack["type"] == "ack"

    db.expire_all()
    row = db.query(FBAgentSession).filter(FBAgentSession.user_id == "u-agent-state").one()
    assert row.status == "ACTIVE"
    assert row.last_ok_at is not None


def test_websocket_route_invalid_token_reaches_handler(client):
    with client.websocket_connect("/ws/fb/agent") as ws:
        ws.send_json({"token": "invalid-token", "agent_id": "a1", "agent_version": "0.1"})
        try:
            ws.receive_json()
            assert False, "websocket should be closed for invalid token"
        except WebSocketDisconnect as exc:
            assert exc.code == 4401


def test_bootstrap_returns_absolute_ws_url(client, db):
    sess = issue_agent_pairing_code(db, "u-agent-abs-url")
    resp = client.get("/auth/facebook/agent/bootstrap", params={"code": sess.pairing_code})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ws_url"].startswith("ws://testserver/")
    assert payload["ws_url"].endswith("ws/fb/agent")
    assert payload["ws_path"] == "/ws/fb/agent"
