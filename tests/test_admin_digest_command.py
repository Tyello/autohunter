import asyncio
import types
import uuid

from app.bot import handlers_admin


class _Msg:
    def __init__(self):
        self.sent = []

    async def reply_text(self, txt):
        self.sent.append(txt)


class _Update:
    def __init__(self, chat_id=1):
        self.effective_chat = types.SimpleNamespace(id=chat_id)
        self.message = _Msg()


class _DBCtx:
    def __init__(self, user=None):
        self._user = user

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def query(self, _model):
        return self

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self._user


def test_admin_digest_non_admin(monkeypatch):
    update = _Update()
    context = types.SimpleNamespace(args=["digest", "user", "123"])
    monkeypatch.setattr("app.bot.handlers_admin.is_admin", lambda _cid: False)
    asyncio.run(handlers_admin.cmd_admin(update, context))
    assert "Sem permissão" in update.message.sent[0]


def test_admin_digest_user_not_found(monkeypatch):
    update = _Update()
    context = types.SimpleNamespace(args=["digest", "user", "123"])
    monkeypatch.setattr("app.bot.handlers_admin.is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _DBCtx(user=None))
    asyncio.run(handlers_admin.cmd_admin(update, context))
    assert "Usuário não encontrado" in update.message.sent[-1]


def test_admin_digest_success_and_day_cap(monkeypatch):
    update = _Update()
    context = types.SimpleNamespace(args=["digest", "user", "123", "999"])
    monkeypatch.setattr("app.bot.handlers_admin.is_admin", lambda _cid: True)
    user = types.SimpleNamespace(id=uuid.uuid4(), telegram_chat_id=123)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _DBCtx(user=user))

    captured = {}

    def _fake_build(_db, *, user_id, days, limit):
        captured["days"] = days
        return {"days": days, "totals": {"sent": 0}}

    monkeypatch.setattr(handlers_admin, "build_weekly_digest_for_user", _fake_build)
    asyncio.run(handlers_admin.cmd_admin(update, context))
    assert captured["days"] == 30
    assert "Sem alertas enviados" in update.message.sent[-1]


def test_admin_digest_candidates_defaults(monkeypatch):
    update = _Update()
    context = types.SimpleNamespace(args=["digest", "candidates"])
    monkeypatch.setattr("app.bot.handlers_admin.is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _DBCtx(user=None))
    captured = {}

    def _fake_candidates(_db, *, days, limit):
        captured["days"] = days
        captured["limit"] = limit
        return []

    monkeypatch.setattr(handlers_admin, "build_weekly_digest_candidates", _fake_candidates)
    asyncio.run(handlers_admin.cmd_admin(update, context))
    assert captured == {"days": 7, "limit": 20}
    assert "Nenhum usuário com alertas enviados" in update.message.sent[-1]


def test_admin_digest_candidates_day_and_limit_cap(monkeypatch):
    update = _Update()
    context = types.SimpleNamespace(args=["digest", "candidates", "999", "999"])
    monkeypatch.setattr("app.bot.handlers_admin.is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _DBCtx(user=None))
    captured = {}

    def _fake_candidates(_db, *, days, limit):
        captured["days"] = days
        captured["limit"] = limit
        return []

    monkeypatch.setattr(handlers_admin, "build_weekly_digest_candidates", _fake_candidates)
    asyncio.run(handlers_admin.cmd_admin(update, context))
    assert captured == {"days": 30, "limit": 50}
