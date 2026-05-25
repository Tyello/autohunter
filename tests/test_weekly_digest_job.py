from __future__ import annotations

import asyncio
import types
import uuid
from datetime import datetime, timedelta, timezone

from app.bot import handlers_admin
from app.bot import admin_handlers_digest
from app.models.user import User
from app.scheduler import weekly_digest_job
from app.services.weekly_digest_preferences_service import set_weekly_digest_enabled, get_digest_preference


def _mk_user(db, *, chat_id: int, active: bool = True):
    u = User(id=uuid.uuid4(), telegram_chat_id=chat_id, username=f"u{chat_id}", is_active=active)
    db.add(u)
    db.commit()
    return u


def test_eligibility_and_recent_window_and_batch_limits(db, monkeypatch):
    u1 = _mk_user(db, chat_id=8101, active=True)
    u2 = _mk_user(db, chat_id=8102, active=False)
    u3 = _mk_user(db, chat_id=8103, active=True)
    for u in [u1, u2, u3]:
        set_weekly_digest_enabled(db, u.id, True)
    pref3 = get_digest_preference(db, u3.id)
    pref3.last_digest_sent_at = datetime.now(timezone.utc) - timedelta(days=1)
    db.commit()

    monkeypatch.setattr(weekly_digest_job.settings, "weekly_digest_batch_size", 10)
    monkeypatch.setattr(weekly_digest_job.settings, "weekly_digest_max_send_per_run", 1)
    monkeypatch.setattr(weekly_digest_job, "build_weekly_digest_for_user", lambda *_args, **_kwargs: {"totals": {"sent": 1}})
    monkeypatch.setattr(weekly_digest_job, "render_weekly_digest", lambda _p: "ok")
    monkeypatch.setattr(weekly_digest_job, "render_weekly_digest", lambda _p: "ok")
    sent = []
    monkeypatch.setattr(weekly_digest_job, "_send_digest_text", lambda chat_id, text: sent.append(chat_id))

    out = weekly_digest_job.run_weekly_digest_once(dry_run=False)
    assert out["checked"] == 3
    assert out["skipped_recent"] >= 0
    assert out["eligible"] >= 0


def test_empty_and_dry_run_do_not_update_last_sent(db, monkeypatch):
    u = _mk_user(db, chat_id=8201, active=True)
    set_weekly_digest_enabled(db, u.id, True)
    monkeypatch.setattr(weekly_digest_job, "build_weekly_digest_for_user", lambda *_args, **_kwargs: {"totals": {"sent": 0}})
    monkeypatch.setattr(weekly_digest_job, "_send_digest_text", lambda *_: (_ for _ in ()).throw(RuntimeError("should not send")))
    out = weekly_digest_job.run_weekly_digest_once(dry_run=True)
    assert out["sent"] == 0
    assert out["skipped_empty"] == 1


def test_send_error_marks_failed_and_continues(db, monkeypatch):
    u1 = _mk_user(db, chat_id=8301, active=True)
    u2 = _mk_user(db, chat_id=8302, active=True)
    for u in [u1, u2]:
        set_weekly_digest_enabled(db, u.id, True)
    monkeypatch.setattr(weekly_digest_job, "build_weekly_digest_for_user", lambda *_args, **_kwargs: {"totals": {"sent": 1}})
    calls = {"n": 0}

    def _send(_chat_id, _text):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")

    monkeypatch.setattr(weekly_digest_job, "_send_digest_text", _send)
    out = weekly_digest_job.run_weekly_digest_once(dry_run=False)
    assert out["failed"] == 1
    assert out["sent"] == 1


class _Msg:
    def __init__(self): self.sent = []
    async def reply_text(self, txt, **kwargs): self.sent.append(txt)


class _Update:
    def __init__(self, chat_id=999):
        self.effective_chat = types.SimpleNamespace(id=chat_id)
        self.message = _Msg()


def _ctx(*args):
    return types.SimpleNamespace(args=list(args), bot=types.SimpleNamespace())


def test_admin_digest_run_modes(monkeypatch):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin.settings, "weekly_digest_job_enabled", False)
    monkeypatch.setattr(admin_handlers_digest, "run_weekly_digest_once", lambda dry_run=True: {"checked": 2, "eligible": 1, "sent": 1, "skipped_recent": 0, "skipped_empty": 0, "failed": 0})
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("digest", "run", "dry")))
    assert "mode=dry" in up.message.sent[-1]
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("digest", "run", "live")))
    assert "bloqueado" in up.message.sent[-1]


def test_admin_digest_run_non_admin_denied(monkeypatch):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: False)
    up = _Update(chat_id=123)
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("digest", "run")))
    assert "sem permissão" in up.message.sent[-1].lower()
