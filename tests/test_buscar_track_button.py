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
    monkeypatch.setattr(handlers, "reply_text", lambda *_args, **_kwargs: asyncio.sleep(0))
    bot_calls = {"n": 0}
    async def _send_message(**kwargs): bot_calls["n"] += 1
    ctx = types.SimpleNamespace(args=["civic"], bot=types.SimpleNamespace(send_message=_send_message))
    asyncio.run(handlers.cmd_buscar(_Update(), ctx))
    assert bot_calls["n"] == 0
