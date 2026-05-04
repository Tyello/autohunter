import asyncio
import types

from app.bot import handlers_admin


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
