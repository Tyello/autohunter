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


def test_admin_auctions_and_source_and_upcoming_and_motos(monkeypatch, db):
    upsert_lot(db, {"source": "vip_auctions", "external_id": "v1", "title": "UNO WAY", "make": "Fiat", "status": "open", "item_type": "car", "year": 2011, "mileage_km": 143129, "url": "https://vip/l1", "extras": {"plate_final": "5"}})
    upsert_lot(db, {"source": "copart_auctions", "external_id": "c1", "title": "CB 500", "make": "Honda", "status": "scheduled", "item_type": "motorcycle", "url": "https://copart/l1"})
    db.commit()

    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions")))
    assert "Total de lotes: 2" in up.message.sent[-1]


def test_admin_auctions_run_variants(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    monkeypatch.setattr(handlers_admin, "run_auction_ingestion", lambda **kwargs: {"source": "vip_auctions", "fetched": 10, "inserted": 2, "updated": 8, "skipped": 0, "errors": 0, "reason": None})
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "run", "vip")))
    assert "Rodando leilões VIP" in up.message.sent[-2]
    assert "limit: 10" in up.message.sent[-1]
    assert "duração_ms:" in up.message.sent[-1]
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "run", "vip", "--limit", "5")))
    assert "Rodando leilões VIP" in up.message.sent[-2]
    assert "limit: 5" in up.message.sent[-1]
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "run", "vip", "--limit", "10", "--enrich")))
    assert "Rodando leilões VIP" in up.message.sent[-2]
    assert "enrich: sim" in up.message.sent[-1]


def test_admin_auctions_run_errors_and_lock(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "run", "copart")))
    assert "não suportada" in up.message.sent[-1]
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "run", "vip", "--limit", "999")))
    assert "Limite inválido" in up.message.sent[-1]

    async def locked_case():
        await handlers_admin._ADMIN_AUCTION_RUN_LOCK.acquire()
        try:
            await handlers_admin.cmd_admin(up, _ctx("auctions", "run", "vip"))
        finally:
            handlers_admin._ADMIN_AUCTION_RUN_LOCK.release()
    asyncio.run(locked_case())
    assert "Já existe uma execução" in up.message.sent[-1]


def test_admin_auctions_run_reason_and_non_admin(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    up = _Update(chat_id=10)
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: False)
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "run", "vip")))
    assert "Sem permissão" in up.message.sent[-1]

    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "run_auction_ingestion", lambda **kwargs: {"source": "vip_auctions", "fetched": 0, "inserted": 0, "updated": 0, "skipped": 0, "errors": 0, "reason": "no_public_lot_cards_found"})
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "run", "vip")))
    assert "Motivo: no_public_lot_cards_found" in up.message.sent[-1]


def test_admin_auctions_run_exception_sends_friendly_error(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))

    def _raise(**_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(handlers_admin, "run_auction_ingestion", _raise)
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "run", "vip", "--limit", "5")))
    assert "Rodando leilões VIP" in up.message.sent[-2]
    assert "Falha ao rodar ingestão de leilões. Verifique logs." in up.message.sent[-1]
