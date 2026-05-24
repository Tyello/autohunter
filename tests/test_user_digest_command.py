import asyncio
import types
import uuid
from datetime import datetime, timezone

from app.bot import handlers_core


class _Msg:
    def __init__(self):
        self.sent = []

    async def reply_text(self, txt, **_kwargs):
        self.sent.append(txt)


class _Update:
    def __init__(self, chat_id=1, username="u"):
        self.effective_chat = types.SimpleNamespace(id=chat_id)
        self.effective_user = types.SimpleNamespace(username=username)
        self.message = _Msg()
        self.effective_message = self.message


class _DBCtx:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _context(args):
    return types.SimpleNamespace(args=args)


def test_digest_status_default(monkeypatch):
    update = _Update()
    state = {"enabled": False, "days": 7, "limit": 10, "sent": None, "preview": None}
    monkeypatch.setattr(handlers_core, "SessionLocal", lambda: _DBCtx())
    monkeypatch.setattr(handlers_core, "get_or_create_user_by_chat", lambda *_a, **_k: types.SimpleNamespace(id=uuid.uuid4()))
    monkeypatch.setattr(handlers_core, "get_or_create_digest_preference", lambda *_a, **_k: types.SimpleNamespace(weekly_digest_enabled=state["enabled"], digest_days=state["days"], digest_limit=state["limit"], last_digest_sent_at=state["sent"], last_digest_previewed_at=state["preview"]))

    asyncio.run(handlers_core.cmd_digest(update, _context(["status"])))
    out = update.message.sent[-1]
    assert "Status: desativado" in out
    assert "a cada 7 dias" in out
    assert "Máximo de itens: 10" in out


def test_digest_on_off(monkeypatch):
    update = _Update()
    state = {"enabled": False}
    monkeypatch.setattr(handlers_core, "SessionLocal", lambda: _DBCtx())
    monkeypatch.setattr(handlers_core, "get_or_create_user_by_chat", lambda *_a, **_k: types.SimpleNamespace(id=uuid.uuid4()))
    monkeypatch.setattr(handlers_core, "get_or_create_digest_preference", lambda *_a, **_k: types.SimpleNamespace(weekly_digest_enabled=state["enabled"], digest_days=7, digest_limit=10, last_digest_sent_at=None, last_digest_previewed_at=None))
    monkeypatch.setattr(handlers_core, "set_weekly_digest_enabled", lambda _db, _uid, enabled: state.update({"enabled": enabled}))

    asyncio.run(handlers_core.cmd_digest(update, _context(["on"])))
    assert state["enabled"] is True
    asyncio.run(handlers_core.cmd_digest(update, _context(["off"])))
    assert state["enabled"] is False


def test_digest_config_and_invalid(monkeypatch):
    update = _Update()
    state = {"days": 7, "limit": 10}
    monkeypatch.setattr(handlers_core, "SessionLocal", lambda: _DBCtx())
    monkeypatch.setattr(handlers_core, "get_or_create_user_by_chat", lambda *_a, **_k: types.SimpleNamespace(id=uuid.uuid4()))
    monkeypatch.setattr(handlers_core, "get_or_create_digest_preference", lambda *_a, **_k: types.SimpleNamespace(weekly_digest_enabled=False, digest_days=state["days"], digest_limit=state["limit"], last_digest_sent_at=None, last_digest_previewed_at=None))

    def _upd(_db, _uid, **kwargs):
        if "days" in kwargs and kwargs["days"] is not None:
            v = kwargs["days"]
            if v < 1 or v > 30:
                raise ValueError("invalid")
            state["days"] = v
        if "limit" in kwargs and kwargs["limit"] is not None:
            v = kwargs["limit"]
            if v < 1 or v > 20:
                raise ValueError("invalid")
            state["limit"] = v

    monkeypatch.setattr(handlers_core, "update_weekly_digest_preferences", _upd)

    asyncio.run(handlers_core.cmd_digest(update, _context(["days", "14"])))
    asyncio.run(handlers_core.cmd_digest(update, _context(["limit", "5"])))
    assert state == {"days": 14, "limit": 5}

    asyncio.run(handlers_core.cmd_digest(update, _context(["days", "50"])))
    assert state == {"days": 14, "limit": 5}
    assert "Valor inválido" in update.message.sent[-1]


def test_digest_preview_marks_preview_no_sent_update(monkeypatch):
    update = _Update()
    user = types.SimpleNamespace(id=uuid.uuid4())
    sent_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    pref = types.SimpleNamespace(weekly_digest_enabled=True, digest_days=14, digest_limit=5, last_digest_sent_at=sent_at, last_digest_previewed_at=None)
    called = {}

    monkeypatch.setattr(handlers_core, "SessionLocal", lambda: _DBCtx())
    monkeypatch.setattr(handlers_core, "get_or_create_user_by_chat", lambda *_a, **_k: user)
    monkeypatch.setattr(handlers_core, "get_or_create_digest_preference", lambda *_a, **_k: pref)

    def _build(_db, *, user_id, days, limit):
        called.update({"user_id": user_id, "days": days, "limit": limit})
        return {"days": days, "totals": {"sent": 0}}

    monkeypatch.setattr(handlers_core, "build_weekly_digest_for_user", _build)
    monkeypatch.setattr(handlers_core, "render_weekly_digest", lambda payload: f"digest {payload['days']}")

    def _mark(_db, _uid):
        pref.last_digest_previewed_at = datetime.now(timezone.utc)

    monkeypatch.setattr(handlers_core, "mark_digest_previewed", _mark)

    asyncio.run(handlers_core.cmd_digest(update, _context(["preview"])))
    assert called["days"] == 14 and called["limit"] == 5 and called["user_id"] == user.id
    assert pref.last_digest_previewed_at is not None
    assert pref.last_digest_sent_at == sent_at


def test_digest_isolated_per_user(monkeypatch):
    users = {111: types.SimpleNamespace(id=uuid.uuid4()), 222: types.SimpleNamespace(id=uuid.uuid4())}
    prefs = {users[111].id: {"enabled": False}, users[222].id: {"enabled": False}}

    monkeypatch.setattr(handlers_core, "SessionLocal", lambda: _DBCtx())
    monkeypatch.setattr(handlers_core, "get_or_create_user_by_chat", lambda _db, chat_id, _u: users[chat_id])
    monkeypatch.setattr(handlers_core, "get_or_create_digest_preference", lambda _db, uid: types.SimpleNamespace(weekly_digest_enabled=prefs[uid]["enabled"], digest_days=7, digest_limit=10, last_digest_sent_at=None, last_digest_previewed_at=None))
    monkeypatch.setattr(handlers_core, "set_weekly_digest_enabled", lambda _db, uid, enabled: prefs[uid].update({"enabled": enabled}))

    asyncio.run(handlers_core.cmd_digest(_Update(chat_id=111), _context(["on"])))
    assert prefs[users[111].id]["enabled"] is True
    assert prefs[users[222].id]["enabled"] is False


def test_digest_default_and_invalid_subcommand(monkeypatch):
    update = _Update()
    monkeypatch.setattr(handlers_core, "SessionLocal", lambda: _DBCtx())
    monkeypatch.setattr(handlers_core, "get_or_create_user_by_chat", lambda *_a, **_k: types.SimpleNamespace(id=uuid.uuid4()))
    monkeypatch.setattr(handlers_core, "get_or_create_digest_preference", lambda *_a, **_k: types.SimpleNamespace(weekly_digest_enabled=False, digest_days=7, digest_limit=10, last_digest_sent_at=None, last_digest_previewed_at=None))

    asyncio.run(handlers_core.cmd_digest(update, _context([])))
    assert "Digest semanal" in update.message.sent[-1]
    asyncio.run(handlers_core.cmd_digest(update, _context(["wat"])))
    assert "Subcomando inválido" in update.message.sent[-1]
