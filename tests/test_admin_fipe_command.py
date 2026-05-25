import asyncio
from types import SimpleNamespace

from app.bot import handlers_admin


class _Msg:
    def __init__(self):
        self.sent = []

    async def reply_text(self, text, **kwargs):
        self.sent.append(text)


class _Up:
    def __init__(self, chat_id):
        self.effective_chat = SimpleNamespace(id=chat_id)
        self.message = _Msg()


def _ctx(*args):
    return SimpleNamespace(args=list(args))


def test_admin_fipe_non_admin(monkeypatch):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: False)
    up = _Up(1)
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("fipe")))
    assert "Sem permissão" in up.message.sent[-1]


def test_admin_fipe_coverage_defaults_and_limit_cap(monkeypatch):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)

    calls = {}

    def _fake(db, reference_month=None, limit=20):
        calls["reference_month"] = reference_month
        calls["limit"] = limit
        return {
            "reference_month": "2026-05",
            "listings_with_fipe_keys": 320,
            "vehicle_keys_distinct": 48,
            "vehicle_keys_covered": 12,
            "coverage_pct": 25,
            "top_missing_keys": [{"vehicle_key": "honda|civic|2015", "count": 18}],
        }

    monkeypatch.setattr(handlers_admin, "build_fipe_coverage_report", _fake)
    up = _Up(1)
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("fipe", "coverage")))
    assert calls["reference_month"] is None
    assert calls["limit"] == 20
    assert "📊 FIPE coverage" in up.message.sent[-1]

    up2 = _Up(1)
    asyncio.run(handlers_admin.cmd_admin(up2, _ctx("fipe", "coverage", "2026-05", "999")))
    assert calls["reference_month"] == "2026-05"
    assert calls["limit"] == 50
