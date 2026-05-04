import asyncio
import types
from datetime import datetime, timedelta, timezone

from app.bot import handlers_admin
from app.models.system_log import SystemLog


class _Msg:
    def __init__(self): self.sent = []
    async def reply_text(self, txt, **_kwargs): self.sent.append(txt)

class _Update:
    def __init__(self, chat_id=1):
        self.effective_chat = types.SimpleNamespace(id=chat_id)
        self.message = _Msg()


def test_admin_audit_guard(monkeypatch):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: False)
    up = _Update(999)
    asyncio.run(handlers_admin._admin_audit(up, []))
    assert "Sem permissão" in up.message.sent[-1]


def test_admin_audit_has_sections(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "sanitize_for_telegram", lambda t: t)
    cap = {"t": ""}
    async def _fake_chunked(_u, text, max_len=3600): cap["t"] = text
    monkeypatch.setattr(handlers_admin, "_reply_chunked", _fake_chunked)
    asyncio.run(handlers_admin._admin_audit(_Update(1), []))
    txt = cap["t"]
    assert "Scheduler:" in txt and "Filas:" in txt and "Notifications:" in txt
    assert "Sources com atenção:" in txt


def test_admin_audit_status_ok(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "sanitize_for_telegram", lambda t: t)
    monkeypatch.setattr(handlers_admin, "collect_operational_alerts", lambda _db, now=None, consume_cooldown=False: [])
    now = datetime.now(timezone.utc)
    db.add(SystemLog(component="scheduler", message="heartbeat", created_at=now - timedelta(minutes=1)))
    db.commit()
    cap = {"t": ""}
    async def _fake_chunked(_u, text, max_len=3600): cap["t"] = text
    monkeypatch.setattr(handlers_admin, "_reply_chunked", _fake_chunked)
    asyncio.run(handlers_admin._admin_audit(_Update(1), []))
    assert "Status geral: OK" in cap["t"]


def test_admin_audit_status_critical(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "sanitize_for_telegram", lambda t: t)
    monkeypatch.setattr(handlers_admin, "collect_operational_alerts", lambda _db, now=None, consume_cooldown=False: [])
    now = datetime.now(timezone.utc)
    db.add(SystemLog(component="scheduler", message="heartbeat", created_at=now - timedelta(hours=4)))
    db.commit()
    cap = {"t": ""}
    async def _fake_chunked(_u, text, max_len=3600): cap["t"] = text
    monkeypatch.setattr(handlers_admin, "_reply_chunked", _fake_chunked)
    asyncio.run(handlers_admin._admin_audit(_Update(1), []))
    assert "Status geral: CRÍTICO" in cap["t"]
