import asyncio
import types

from app.bot import handlers_admin
from app.bot.admin_dedupe_diagnostics import (
    parse_dedupe_collisions_limit,
    render_cross_source_dedupe_collisions,
)


class _Msg:
    def __init__(self):
        self.sent = []

    async def reply_text(self, txt):
        self.sent.append(txt)


class _Update:
    def __init__(self, chat_id=1):
        self.effective_chat = types.SimpleNamespace(id=chat_id)
        self.message = _Msg()


def _ctx(*args):
    return types.SimpleNamespace(args=list(args))


def test_render_cross_source_collisions_empty():
    out = render_cross_source_dedupe_collisions([])
    assert "Nenhuma colisão cross-source encontrada agora." in out
    assert "- suppression enabled: false" in out
    assert "- shadow mode: true" in out


def test_render_cross_source_collisions_with_examples_and_truncation():
    collisions = [
        {
            "fingerprint": "abc123456789012345678901",
            "listing_count": 4,
            "source_count": 2,
            "sources": ["olx", "mercadolivre"],
            "examples": [
                {"source": "olx", "title": "Honda Civic EX 2019 " + ("muito longo " * 8), "price": 80000, "mileage_km": 82000},
                {"source": "mercadolivre", "title": "Honda Civic EX 2019", "price": 80500, "mileage_km": 81000},
                {"source": "icarros", "title": "Honda Civic EX 2019", "price": 79900, "mileage_km": 82500},
                {"source": "webmotors", "title": "Não deve aparecer", "price": 90000, "mileage_km": 70000},
            ],
        }
    ]
    out = render_cross_source_dedupe_collisions(collisions)
    assert "[1] abc123456789012345678901" in out
    assert "Sources (2): olx, mercadolivre" in out
    assert "Listings: 4" in out
    assert "Não deve aparecer" not in out
    assert "…" in out


def test_parse_limit_defaults_and_caps():
    assert parse_dedupe_collisions_limit([]) == 10
    assert parse_dedupe_collisions_limit(["collisions"]) == 10
    assert parse_dedupe_collisions_limit(["collisions", "18"]) == 18
    assert parse_dedupe_collisions_limit(["collisions", "999"]) == 20
    assert parse_dedupe_collisions_limit(["collisions", "oops"]) == 10


def test_admin_dedupe_denies_non_admin(monkeypatch):
    up = _Update(chat_id=99)
    monkeypatch.setattr("app.bot.handlers_admin.is_admin", lambda _cid: False)
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("dedupe")))
    assert up.message.sent[-1] == "Sem permissão."


def test_admin_dedupe_calls_service_and_renders(monkeypatch):
    up = _Update(chat_id=1)
    monkeypatch.setattr("app.bot.handlers_admin.is_admin", lambda _cid: True)

    calls = {}

    class _DummySession:
        def __enter__(self):
            return object()

        def __exit__(self, exc_type, exc, tb):
            return False

    def _fake_find(_db, limit=0):
        calls["limit"] = limit
        return [{"fingerprint": "abc", "listing_count": 2, "source_count": 2, "sources": ["olx", "mercadolivre"], "examples": []}]

    monkeypatch.setattr("app.bot.handlers_admin.SessionLocal", _DummySession)
    monkeypatch.setattr("app.bot.handlers_admin.find_cross_source_fingerprint_collisions", _fake_find)
    monkeypatch.setattr("app.bot.handlers_admin.settings.cross_source_dedupe_enabled", False)
    monkeypatch.setattr("app.bot.handlers_admin.settings.cross_source_dedupe_shadow_mode", True)
    monkeypatch.setattr("app.bot.handlers_admin.settings.cross_source_dedupe_window_days", 30)

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("dedupe", "collisions", "999")))
    assert calls["limit"] == 20
    assert "[1] abc" in up.message.sent[-1]
    assert "- suppression enabled: false" in up.message.sent[-1]
