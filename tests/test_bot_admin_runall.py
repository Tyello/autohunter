import asyncio
from types import SimpleNamespace

from app.bot import handlers_admin as mod


class _Msg:
    def __init__(self):
        self.texts = []

    async def reply_text(self, text):
        self.texts.append(text)


class _Update:
    def __init__(self):
        self.effective_chat = SimpleNamespace(id=1)
        self.message = _Msg()


class _DB:
    def query(self, _model):
        class _Q:
            def all(self):
                return []
        return _Q()


class _Ctx:
    def __enter__(self):
        return _DB()

    def __exit__(self, exc_type, exc, tb):
        return False


def test_admin_runall_renders_runtime_impl(monkeypatch):
    monkeypatch.setattr(mod, "is_admin", lambda _id: True)
    monkeypatch.setattr(mod, "list_sources", lambda: [SimpleNamespace(name="mercadolivre", scrape=lambda *_a, **_k: [])])
    monkeypatch.setattr(mod, "SessionLocal", lambda: _Ctx())
    monkeypatch.setattr(mod, "ensure_source_configs", lambda _db: None)
    monkeypatch.setattr(
        mod,
        "run_source_for_all_wishlists",
        lambda *_a, **_k: {
            "status": "success",
            "found": 186,
            "inserted": 5,
            "matched": 8,
            "queued": 0,
            "duration_ms": 87132,
            "runtime_impl": "v2_canary",
            "run_summary": {"status": "OK", "found": 186, "inserted": 5, "matched": 8, "queued": 0},
        },
    )

    up = _Update()
    asyncio.run(mod._admin_runall(up, ["mercadolivre"]))

    text = "\n".join(up.message.texts)
    assert "impl=v2_canary" in text
