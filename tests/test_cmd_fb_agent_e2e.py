from __future__ import annotations

import asyncio
import types

from app.bot import handlers_fb_agent
from app.models.fb_agent_session import FBAgentSession


class _Message:
    def __init__(self):
        self.sent: list[dict] = []

    async def reply_text(self, text, reply_markup=None):
        self.sent.append({"text": text, "reply_markup": reply_markup})


class _Update:
    def __init__(self, telegram_user_id, has_user=True):
        self.message = _Message()
        self.effective_message = self.message
        self.effective_chat = types.SimpleNamespace(id=telegram_user_id)
        self.effective_user = (
            types.SimpleNamespace(id=telegram_user_id, username="tester") if has_user else None
        )


class _DBSessionWrapper:
    def __init__(self, db):
        self._db = db

    def __enter__(self):
        return self._db

    def __exit__(self, *_exc):
        return None


def _use_real_db(monkeypatch, db):
    monkeypatch.setattr(handlers_fb_agent, "SessionLocal", lambda: _DBSessionWrapper(db))


def _ctx(args=None):
    return types.SimpleNamespace(args=args or [])


def test_cmd_fb_no_args_shows_usage():
    update = _Update(1001)
    asyncio.run(handlers_fb_agent.cmd_fb(update, _ctx([])))
    assert "/fb connect" in update.message.sent[-1]["text"]


def test_cmd_fb_invalid_effective_user():
    update = _Update(1002, has_user=False)
    asyncio.run(handlers_fb_agent.cmd_fb(update, _ctx(["status"])))
    assert "usuário inválido" in update.message.sent[-1]["text"].lower()


def test_cmd_fb_invalid_action(db, monkeypatch):
    _use_real_db(monkeypatch, db)
    update = _Update(1003)
    asyncio.run(handlers_fb_agent.cmd_fb(update, _ctx(["bogus"])))
    assert "ação inválida" in update.message.sent[-1]["text"].lower()


def test_cmd_fb_status_without_session_prompts_connect(db, monkeypatch):
    _use_real_db(monkeypatch, db)
    update = _Update(1004)
    asyncio.run(handlers_fb_agent.cmd_fb(update, _ctx(["status"])))
    assert "/fb connect" in update.message.sent[-1]["text"]


def test_cmd_fb_disconnect_without_session_reports_none(db, monkeypatch):
    _use_real_db(monkeypatch, db)
    update = _Update(1005)
    asyncio.run(handlers_fb_agent.cmd_fb(update, _ctx(["disconnect"])))
    assert "nenhuma sessão" in update.message.sent[-1]["text"].lower()


def test_cmd_fb_connect_issues_pairing_code(db, monkeypatch):
    _use_real_db(monkeypatch, db)
    telegram_user_id = 1006
    update = _Update(telegram_user_id)
    asyncio.run(handlers_fb_agent.cmd_fb(update, _ctx(["connect"])))

    text = update.message.sent[-1]["text"]
    assert "código" in text.lower()
    assert "link" in text.lower()

    sess = db.query(FBAgentSession).filter(FBAgentSession.user_id == str(telegram_user_id)).one_or_none()
    assert sess is not None
    assert sess.status == "PENDING_AGENT"
    assert sess.pairing_code and sess.pairing_code in text


def test_cmd_fb_status_after_connect_shows_pending(db, monkeypatch):
    _use_real_db(monkeypatch, db)
    telegram_user_id = 1007
    update = _Update(telegram_user_id)
    asyncio.run(handlers_fb_agent.cmd_fb(update, _ctx(["connect"])))

    status_update = _Update(telegram_user_id)
    asyncio.run(handlers_fb_agent.cmd_fb(status_update, _ctx(["status"])))
    text = status_update.message.sent[-1]["text"]
    assert "status=PENDING_AGENT" in text


def test_cmd_fb_disconnect_after_connect_disables_session(db, monkeypatch):
    _use_real_db(monkeypatch, db)
    telegram_user_id = 1008
    update = _Update(telegram_user_id)
    asyncio.run(handlers_fb_agent.cmd_fb(update, _ctx(["connect"])))

    disconnect_update = _Update(telegram_user_id)
    asyncio.run(handlers_fb_agent.cmd_fb(disconnect_update, _ctx(["disconnect"])))
    assert "desconectado" in disconnect_update.message.sent[-1]["text"].lower()

    sess = db.query(FBAgentSession).filter(FBAgentSession.user_id == str(telegram_user_id)).one_or_none()
    assert sess.status == "DISABLED"
