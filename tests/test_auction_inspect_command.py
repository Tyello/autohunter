import asyncio
import types

from app.bot import handlers_admin


class _Msg:
    def __init__(self):
        self.sent = []

    async def reply_text(self, txt, **kwargs):
        self.sent.append(txt)


class _Update:
    def __init__(self, chat_id=999):
        self.effective_chat = types.SimpleNamespace(id=chat_id)
        self.message = _Msg()


def _ctx(*args):
    return types.SimpleNamespace(args=list(args), bot=types.SimpleNamespace())


def test_admin_auctions_inspect_render_and_non_admin(monkeypatch):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(
        handlers_admin,
        "inspect_auction_source",
        lambda **kwargs: {
            "source": "win_auctions",
            "fetched": 1,
            "candidates": [
                {
                    "index": 1,
                    "url": "https://x/l1",
                    "title": None,
                    "title_fallback": "Honda Civic 2015",
                    "external_id": "1",
                    "item_type": "car",
                    "current_bid": None,
                    "initial_bid": None,
                    "year": 2015,
                    "status": "open",
                    "skip_reason": "missing_title",
                    "text_preview": "preview",
                }
            ],
        },
    )

    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "inspect", "win", "--limit", "5")))
    text = up.message.sent[-1]
    assert "inspect win_auctions" in text
    assert "skip_reason: missing_title" in text
    assert "text_preview: preview" in text
    assert "browser:" not in text

    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: False)
    up2 = _Update(chat_id=10)
    asyncio.run(handlers_admin.cmd_admin(up2, _ctx("auctions", "inspect", "win")))
    assert "Sem permissão" in up2.message.sent[-1]
