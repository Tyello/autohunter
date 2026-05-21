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
    events = []
    monkeypatch.setattr(handlers, "SessionLocal", lambda: _Session())
    async def _reply(*_args, **_kwargs):
        events.append("reply")
    monkeypatch.setattr(handlers, "reply_text", _reply)
    def _manual_search(*_args, **_kwargs):
        events.append("manual_search")
        return []
    monkeypatch.setattr(handlers, "_run_manual_search_sync", _manual_search)
    async def _send_message(**kwargs):
        events.append("send_result")
    scheduled = {"coro": None}
    def _capture_create_task(coro):
        scheduled["coro"] = coro
        events.append("task_scheduled")
        return types.SimpleNamespace()
    monkeypatch.setattr(handlers.asyncio, "create_task", _capture_create_task)
    ctx = types.SimpleNamespace(args=["civic"], bot=types.SimpleNamespace(send_message=_send_message))
    asyncio.run(handlers.cmd_buscar(_Update(), ctx))
    assert events[0] == "reply"
    assert "manual_search" not in events
    assert "task_scheduled" in events
    if scheduled["coro"] is not None:
        scheduled["coro"].close()


def test_run_manual_search_sync_preserves_open_link_button(monkeypatch):
    monkeypatch.setattr(handlers, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(handlers, "get_or_create_user_by_chat", lambda *_: types.SimpleNamespace(id="u1"))
    monkeypatch.setattr(handlers, "list_wishlists", lambda *_: [])
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
    payloads, debug = handlers._run_manual_search_sync(chat_id=1, username="u", query="civic", sources=None)
    assert payloads
    assert debug["cleaned_query"] == "civic"
    assert payloads[0]["inline_keyboard"][0][0]["url"] == "https://x"
    assert all(b.get("text") != "⭐ Rastrear" for row in payloads[0]["inline_keyboard"] for b in row)


def test_run_manual_search_sync_one_active_wishlist_adds_direct_track_button(monkeypatch):
    monkeypatch.setattr(handlers, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(handlers, "get_or_create_user_by_chat", lambda *_: types.SimpleNamespace(id="u1"))
    monkeypatch.setattr(handlers, "list_wishlists", lambda *_: [types.SimpleNamespace(id="w1", is_active=True)])
    monkeypatch.setattr(handlers, "issue_tracking_callback_token", lambda **_kwargs: "tok123")
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
    payloads, _ = handlers._run_manual_search_sync(chat_id=1, username="u", query="civic", sources=None)
    buttons = [b for row in payloads[0]["inline_keyboard"] for b in row]
    assert any(b.get("text") == "Abrir anúncio" for b in buttons)
    assert any(b.get("callback_data") == "TRACK:ADDT:tok123" for b in buttons)


def test_run_manual_search_sync_multi_active_wishlist_adds_choose_track_button(monkeypatch):
    monkeypatch.setattr(handlers, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(handlers, "get_or_create_user_by_chat", lambda *_: types.SimpleNamespace(id="u1"))
    monkeypatch.setattr(
        handlers,
        "list_wishlists",
        lambda *_: [types.SimpleNamespace(id="w1", is_active=True), types.SimpleNamespace(id="w2", is_active=True)],
    )
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
    payloads, _ = handlers._run_manual_search_sync(chat_id=1, username="u", query="civic", sources=None)
    buttons = [b for row in payloads[0]["inline_keyboard"] for b in row]
    assert any((b.get("callback_data") or "").startswith("TRACK:CHOOSE:c1") for b in buttons)


def test_run_manual_search_sync_paused_wishlist_does_not_count(monkeypatch):
    monkeypatch.setattr(handlers, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(handlers, "get_or_create_user_by_chat", lambda *_: types.SimpleNamespace(id="u1"))
    monkeypatch.setattr(handlers, "list_wishlists", lambda *_: [types.SimpleNamespace(id="w1", is_active=False)])
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
    payloads, _ = handlers._run_manual_search_sync(chat_id=1, username="u", query="civic", sources=None)
    buttons = [b for row in payloads[0]["inline_keyboard"] for b in row]
    assert not any(b.get("text") == "⭐ Rastrear" for b in buttons)


def test_buscar_sends_results_when_found(monkeypatch):
    sent = []
    async def _reply(*_args, **_kwargs):
        return None
    async def _send_message(**kwargs):
        sent.append(kwargs["text"])
    monkeypatch.setattr(handlers, "reply_text", _reply)
    monkeypatch.setattr(handlers, "_run_manual_search_sync", lambda **_kwargs: ([{"text": "resultado", "inline_keyboard": []}], {}))
    created = {}
    def _capture(coro):
        created["coro"] = coro
        return types.SimpleNamespace()
    monkeypatch.setattr(handlers.asyncio, "create_task", _capture)
    ctx = types.SimpleNamespace(args=["civic"], bot=types.SimpleNamespace(send_message=_send_message))
    asyncio.run(handlers.cmd_buscar(_Update(), ctx))
    asyncio.run(created["coro"])
    assert "resultado" in sent


def test_buscar_sends_not_found_when_empty(monkeypatch):
    sent = []
    async def _reply(*_args, **_kwargs):
        return None
    async def _send_message(**kwargs):
        sent.append(kwargs["text"])
    monkeypatch.setattr(handlers, "reply_text", _reply)
    monkeypatch.setattr(handlers, "_run_manual_search_sync", lambda **_kwargs: ([], {}))
    created = {}
    def _capture(coro):
        created["coro"] = coro
        return types.SimpleNamespace()
    monkeypatch.setattr(handlers.asyncio, "create_task", _capture)
    ctx = types.SimpleNamespace(args=["civic"], bot=types.SimpleNamespace(send_message=_send_message))
    asyncio.run(handlers.cmd_buscar(_Update(), ctx))
    asyncio.run(created["coro"])
    assert any("Não encontrei anúncios" in t for t in sent)
