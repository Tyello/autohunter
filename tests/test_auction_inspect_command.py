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


def test_admin_auctions_inspect_with_detail_url_passes_param(monkeypatch):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    seen = {}

    def _inspect(**kwargs):
        seen.update(kwargs)
        return {"source": "win_auctions", "fetched": 0, "reason": "detail_without_extractable_signals", "candidates": []}

    monkeypatch.setattr(handlers_admin, "inspect_auction_source", _inspect)
    up = _Update()
    detail_url = "https://www.winleiloes.com.br/item/4042/detalhes?page=1"
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "inspect", "win", "--url", detail_url)))
    assert seen.get("detail_url") == detail_url


def test_admin_auctions_inspect_renders_endpoint_candidates_and_preview(monkeypatch):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(
        handlers_admin,
        "inspect_auction_source",
        lambda **kwargs: {
            "source": "win_auctions",
            "fetched": 0,
            "reason": "requires_js_or_endpoint_study",
            "diagnostics": {
                "url": "https://www.winleiloes.com.br/lotes/veiculo?tipo=veiculo&categoria_id=8",
                "status_code": 200,
                "content_type": "text/html",
                "content_length": 1200,
                "html_title": "Busca de Veículos :: Win Leilões",
                "html_preview": "preview truncado",
                "hints": {
                    "has_script_tags": True,
                    "possible_js_app": True,
                    "possible_api_endpoints": ["/lotes/veiculo", "/api/lotes", "/search"],
                    "lot_detail_candidates": ["/item/4042/detalhes"],
                    "lot_image_candidates": ["https://x.cloudfront.net/watermark/bens/4042.jpg"],
                },
            },
            "candidates": [],
        },
    )
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "inspect", "win", "--limit", "5")))
    text = up.message.sent[-1]
    assert "reason: requires_js_or_endpoint_study" in text
    assert "endpoint_candidates_top:" in text
    assert "lot_detail_candidates_top:" in text
    assert "lot_image_candidates_top:" in text
    assert "Preview HTML:" in text
