import asyncio
import types
from app.bot import handlers

class _Session:
    def __enter__(self): return self
    def __exit__(self, *_): return None

class _Update:
    def __init__(self):
        self.effective_chat = types.SimpleNamespace(id=1)
        self.effective_user = types.SimpleNamespace(username="u")
        self.message = types.SimpleNamespace()

def test_buscar_responds_immediately(monkeypatch):
    monkeypatch.setattr(handlers, "SessionLocal", lambda: _Session())
    sent = {"n": 0}
    async def _reply(*_args, **_kwargs): sent["n"] += 1
    monkeypatch.setattr(handlers, "reply_text", _reply)
    bot_calls = {"n": 0}
    async def _send_message(**kwargs): bot_calls["n"] += 1
    ctx = types.SimpleNamespace(args=["civic"], bot=types.SimpleNamespace(send_message=_send_message))
    asyncio.run(handlers.cmd_buscar(_Update(), ctx))
    assert sent["n"] == 1
    assert bot_calls["n"] <= 1


def test_run_manual_search_sync_preserves_open_link_button(monkeypatch):
    monkeypatch.setattr(handlers, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(handlers, "get_or_create_user_by_chat", lambda *_: types.SimpleNamespace(id="u1"))
    monkeypatch.setattr(
        handlers,
        "manual_search",
        lambda *_args, **_kwargs: [types.SimpleNamespace(id="c1", title="t", price=1, source="olx", url="https://x", external_id="e1", thumbnail_url=None)],
    )
    monkeypatch.setattr(handlers, "batch_get_market_stats", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(handlers, "cohort_key_for_listing", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(handlers, "score_ad", lambda *_: types.SimpleNamespace(total=0, to_dict=lambda: {}))
    monkeypatch.setattr(
        handlers,
        "format_ad_message",
        lambda *_args, **_kwargs: types.SimpleNamespace(text="resultado", inline_keyboard=[[{"text": "Abrir anúncio", "url": "https://x"}]]),
    )
    payloads = handlers._run_manual_search_sync(chat_id=1, username="u", query="civic", sources=None)
    assert payloads
    assert payloads[0]["inline_keyboard"][0][0]["url"] == "https://x"
