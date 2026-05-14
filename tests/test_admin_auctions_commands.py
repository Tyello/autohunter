import asyncio
import types

from app.bot import handlers_admin
from app.bot.renderers import render_admin_auctions_summary
from app.services.auction_lot_service import upsert_lot


class _Msg:
    def __init__(self):
        self.sent = []

    async def reply_text(self, txt, **kwargs):
        self.sent.append(txt)


class _Update:
    def __init__(self, chat_id=999):
        self.effective_chat = types.SimpleNamespace(id=chat_id)
        self.message = _Msg()


class _SessionWrap:
    def __init__(self, db):
        self.db = db
    def __enter__(self):
        return self.db
    def __exit__(self, *_):
        return False


def _ctx(*args):
    return types.SimpleNamespace(args=list(args), bot=types.SimpleNamespace())


def test_render_admin_auctions_summary_empty():
    text = render_admin_auctions_summary({"total_lots": 0, "by_source": {}, "by_status": {}, "by_item_type": {}}, [])
    assert "Total de lotes: 0" in text
    assert "Nenhum lote persistido ainda." in text


def test_render_admin_auctions_summary_with_lots(db):
    lot, _ = upsert_lot(db, {"source": "vip_auctions", "external_id": "v1", "title": "UNO", "status": "open", "item_type": "car"})
    db.commit()
    stats = {"total_lots": 1, "by_source": {"vip_auctions": 1}, "by_status": {"open": 1}, "by_item_type": {"car": 1}}
    text = render_admin_auctions_summary(stats, [lot])
    assert "vip_auctions: 1" in text
    assert "open: 1" in text
    assert "car: 1" in text


def test_admin_auctions_and_source_and_upcoming_and_motos(monkeypatch, db):
    upsert_lot(db, {"source": "vip_auctions", "external_id": "v1", "title": "UNO WAY", "make": "Fiat", "status": "open", "item_type": "car", "year": 2011, "mileage_km": 143129, "url": "https://vip/l1", "extras": {"plate_final": "5"}})
    upsert_lot(db, {"source": "copart_auctions", "external_id": "c1", "title": "CB 500", "make": "Honda", "status": "scheduled", "item_type": "motorcycle", "url": "https://copart/l1"})
    db.commit()

    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    up = _Update()

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions")))
    assert "Total de lotes: 2" in up.message.sent[-1]

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "source", "vip")))
    assert "source vip_auctions" in up.message.sent[-1]
    assert "UNO WAY" in up.message.sent[-1]

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "upcoming")))
    assert "Sem data de encerramento capturada nesta fase." in up.message.sent[-1]

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "motos")))
    assert "CB 500" in up.message.sent[-1]


def test_admin_auctions_motos_empty_and_non_admin(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    up = _Update(chat_id=10)

    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: False)
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions")))
    assert "Sem permissão." in up.message.sent[-1]

    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "motos")))
    assert "Não há lotes de motos persistidos ainda." in up.message.sent[-1]
