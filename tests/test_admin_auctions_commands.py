import asyncio
import types
import uuid
from datetime import datetime, timedelta, timezone

from app.bot import handlers_admin
from app.models.app_kv import AppKV
from app.models.auction_lot import AuctionLot
from app.models.source_config import SourceConfig
from app.models.system_log import SystemLog
from app.models.user import User
from app.models.wishlist import Wishlist
from app.services.app_kv_service import set_kv
from app.bot.renderers import render_admin_auction_lot, render_admin_auctions_summary
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


def test_admin_upcoming_orders_by_end_at_and_shows_sections(monkeypatch, db):
    upsert_lot(db, {"source": "vip_auctions", "external_id": "v1", "title": "A", "auction_end_at": datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)})
    upsert_lot(db, {"source": "vip_auctions", "external_id": "v2", "title": "B", "auction_end_at": datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc)})
    upsert_lot(db, {"source": "vip_auctions", "external_id": "v3", "title": "C"})
    db.commit()
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "upcoming")))
    text = up.message.sent[-1]
    assert "próximos encerramentos" in text
    assert text.index("\nB\n") < text.index("\nA\n")
    assert "Sem encerramento capturado:" in text


def test_admin_upcoming_without_end_at_keeps_fallback(monkeypatch, db):
    upsert_lot(db, {"source": "vip_auctions", "external_id": "v1", "title": "A"})
    db.commit()
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "upcoming")))
    assert "Sem data de encerramento capturada nesta fase." in up.message.sent[-1]


def test_render_admin_auction_lot_shows_start_and_end():
    lot = types.SimpleNamespace(
        title="X",
        source="vip_auctions",
        make="Fiat",
        item_type="car",
        status="open",
        auction_start_at=datetime(2026, 5, 15, 10, 0, tzinfo=timezone.utc),
        auction_end_at=datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc),
        url="https://vip/l1",
        extras={},
    )
    text = render_admin_auction_lot(lot)
    assert "Início:" in text
    assert "Encerra:" in text



def test_render_admin_auction_lot_shows_start_without_end_label():
    lot = types.SimpleNamespace(
        title="X",
        source="win_auctions",
        make="Fiat",
        item_type="car",
        status="live",
        auction_start_at=datetime(2026, 5, 21, 11, 0, tzinfo=timezone.utc),
        auction_end_at=None,
        url="https://win/l1",
        extras={},
    )
    text = render_admin_auction_lot(lot)
    assert "Início:" in text
    assert "Encerra:" not in text

def test_admin_auctions_run_variants(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    monkeypatch.setattr(handlers_admin, "run_auction_ingestion", lambda **kwargs: {"source": "vip_auctions", "fetched": 10, "inserted": 2, "updated": 8, "skipped": 4, "errors": 0, "reason": None, "skipped_reasons": {"invalid_url": 2, "institutional_url": 2}, "ignored_examples": [{"reason": "missing_title", "source": "vip_auctions", "url": "https://vip/item/1", "title": "-", "fallback_title": "Uno", "text_preview": "card text"}]})
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "run", "vip")))
    assert "Rodando leilões vip_auctions" in up.message.sent[-2]
    assert "limit: 10" in up.message.sent[-1]
    assert "duração_ms:" in up.message.sent[-1]
    assert "Ignorados:" in up.message.sent[-1]
    assert "ignored_examples:" in up.message.sent[-1]
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "run", "vip", "--limit", "5")))
    assert "Rodando leilões vip_auctions" in up.message.sent[-2]
    assert "limit: 5" in up.message.sent[-1]
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "run", "vip", "--limit", "10", "--enrich")))
    assert "Rodando leilões vip_auctions" in up.message.sent[-2]
    assert "enrich: sim" in up.message.sent[-1]

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "run", "win", "--limit", "10")))
    assert "Rodando leilões win_auctions" in up.message.sent[-2]

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "run", "sodre", "--limit", "10")))
    assert "Rodando leilões sodre_auctions" in up.message.sent[-2]

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "run", "superbid", "--limit", "10")))
    assert "Rodando leilões superbid_auctions" in up.message.sent[-2]



def test_admin_auctions_run_errors_and_lock(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "run", "invalida")))
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
    assert "Rodando leilões vip_auctions" in up.message.sent[-2]
    assert "Falha ao rodar ingestão de leilões: RuntimeError — boom" in up.message.sent[-1]


def test_admin_auctions_inspect_mega_url_renders_detail_diagnostics(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    monkeypatch.setattr(
        handlers_admin,
        "inspect_auction_source",
        lambda **kwargs: {
            "source": "mega_auctions",
            "fetched": 1,
            "inserted": 0,
            "updated": 0,
            "skipped": 0,
            "errors": 0,
            "reason": None,
            "candidates": [{"index": 1, "external_id": "J122290", "title": "Volkswagen Kombi", "detail_url": "https://mega/x", "item_type": "car", "year": 1999}],
            "diagnostics": {"detail_diagnostics": {"mega_detail": {"status_candidates": ["Status: encerrado"]}}},
        },
    )
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "inspect", "mega", "--url", "https://mega/x")))
    text = up.message.sent[-1]
    assert "detail_url: https://mega/x" in text
    assert len(text) < 4096


def test_admin_auctions_match_variants(monkeypatch, db):
    from app.models.user import User
    from app.models.wishlist import Wishlist

    u = User(id=uuid.uuid4(), telegram_chat_id=901, username="x")
    db.add(u)
    db.flush()
    w = Wishlist(user_id=u.id, query="civic 2015", is_active=True, include_auctions=True)
    db.add(w)
    db.flush()
    upsert_lot(db, {"source": "vip_auctions", "external_id": "m1", "title": "Honda Civic 2015", "year": 2015, "status": "open", "current_bid": 91000})
    upsert_lot(db, {"source": "vip_auctions", "external_id": "m2", "title": "Honda Civic EX 2015", "year": 2015, "status": "open"})
    db.commit()

    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    up = _Update()

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "match")))
    assert "matching (somente leitura)" in up.message.sent[-1] or "Sem leilões compatíveis" in up.message.sent[-1]

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "match", "vip")))
    assert "VIP" in up.message.sent[-1]

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "match", "win")))
    assert "matching (somente leitura)" in up.message.sent[-1] or "Sem leilões compatíveis" in up.message.sent[-1]

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "source", "mega")))
    assert "source mega_auctions" in up.message.sent[-1] or "Nenhum lote persistido para source=mega_auctions" in up.message.sent[-1]


def test_admin_auctions_hygiene_mega_dry_run_does_not_change_db(monkeypatch, db):
    upsert_lot(db, {"source": "mega_auctions", "external_id": "h1", "title": "Leiloes Judiciais", "url": "https://www.megaleiloes.com.br/leiloes-judiciais", "item_type": "motorcycle"})
    db.commit()
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "hygiene", "mega", "--dry-run")))
    text = up.message.sent[-1]
    assert "hygiene mega_auctions" in text
    assert "- generic_page: 1" in text
    lot = db.query(AuctionLot).filter(AuctionLot.source == "mega_auctions", AuctionLot.external_id == "h1").first()
    assert lot.status != "invalid"


def test_admin_auctions_hygiene_mega_dry_run_no_change_any_status(monkeypatch, db):
    cfg = db.query(SourceConfig).filter(SourceConfig.source == "mega_auctions", SourceConfig.source_type == "auction").first()
    if cfg:
        cfg.status = "production_ready"
    else:
        db.add(SourceConfig(source="mega_auctions", source_type="auction", is_enabled=True, user_eligible=False, status="production_ready"))
    upsert_lot(db, {"source": "mega_auctions", "external_id": "h1b", "title": "Leiloes Judiciais", "url": "https://www.megaleiloes.com.br/leiloes-judiciais", "item_type": "motorcycle"})
    db.commit()
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "hygiene", "mega", "--dry-run")))
    lot = db.query(AuctionLot).filter(AuctionLot.source == "mega_auctions", AuctionLot.external_id == "h1b").first()
    assert lot.status != "invalid"
    assert lot.item_type == "motorcycle"


def test_admin_auctions_hygiene_mega_apply_updates_safe_fields(monkeypatch, db):
    upsert_lot(db, {"source": "mega_auctions", "external_id": "h2", "title": "Direitos Sobre Carro Renault Sandero", "url": "https://www.megaleiloes.com.br/veiculos/carros/si/sem-informacao/x-j121066", "item_type": "motorcycle", "city": "SI", "state": "SI", "location": "Sem informação, SI"})
    db.commit()
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "hygiene", "mega", "--apply")))
    lot = db.query(AuctionLot).filter(AuctionLot.source == "mega_auctions", AuctionLot.external_id == "h2").first()
    assert lot.item_type == "car"
    assert lot.city is None and lot.state is None and lot.location is None


def test_admin_auctions_hygiene_mega_apply_blocked_when_not_experimental(monkeypatch, db):
    cfg = db.query(SourceConfig).filter(SourceConfig.source == "mega_auctions", SourceConfig.source_type == "auction").first()
    if cfg:
        cfg.status = "production_ready"
    else:
        db.add(SourceConfig(source="mega_auctions", source_type="auction", is_enabled=True, user_eligible=False, status="production_ready"))
    upsert_lot(db, {"source": "mega_auctions", "external_id": "h3", "title": "Leiloes Judiciais", "url": "https://www.megaleiloes.com.br/leiloes-judiciais", "item_type": "motorcycle", "city": "X", "state": "SP", "location": "X, SP"})
    db.commit()
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    monkeypatch.setattr(handlers_admin, "ensure_auction_source_configs", lambda _db: 0)
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "hygiene", "mega", "--apply")))
    text = up.message.sent[-1]
    assert "bloqueado: sim (source_not_experimental)" in text
    assert "atualizados: 0" in text
    lot = db.query(AuctionLot).filter(AuctionLot.source == "mega_auctions", AuctionLot.external_id == "h3").first()
    assert lot.item_type == "motorcycle"
    assert lot.status != "invalid"
    assert lot.location == "X, SP"




def test_admin_auctions_source_invalid_shows_registry_hint(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))


def test_admin_auctions_settings_blocks_dry_run_false(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "settings", "set", "dry_run", "false")))
    assert "ainda não é permitido" in up.message.sent[-1]
    row = db.query(AppKV).filter(AppKV.key == "auction_notification_settings").first()
    assert not row or row.value.get("dry_run") is not False


def test_admin_auctions_settings_allows_dry_run_true(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "settings", "set", "dry_run", "true")))
    row = db.query(AppKV).filter(AppKV.key == "auction_notification_settings").first()
    assert row and row.value.get("dry_run") is True
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "source", "invalida")))
    assert up.message.sent[-1] == "Source de leilão não suportada. Use: vip|mega|win|sodre|superbid|copart"


def test_admin_auctions_match_invalid_source_shows_error(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "match", "fonte_invalida")))
    assert up.message.sent[-1] == "Source de leilão não suportada. Use: vip|mega|win|sodre|superbid|copart"
def test_admin_auctions_match_wishlist_invalid_id(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "match", "wishlist", "invalido")))
    assert up.message.sent[-1] == "Wishlist não encontrada."


def test_admin_auctions_match_non_admin_and_empty(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    up = _Update(chat_id=10)
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: False)
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "match")))
    assert "Sem permissão" in up.message.sent[-1]

    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "match")))
    assert "Sem leilões compatíveis" in up.message.sent[-1]


def test_admin_auctions_quality_variants(monkeypatch, db):
    upsert_lot(db, {"source": "vip_auctions", "external_id": "v1", "title": "UNO", "year": 2011, "current_bid": 10, "url": "https://vip/1", "status": "open"})
    upsert_lot(db, {"source": "mega_auctions", "external_id": "m1", "title": "PALIO", "url": "https://mega/1"})
    db.commit()

    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    up = _Update()

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "quality")))
    assert "Admin Leilões — qualidade" in up.message.sent[-1]
    assert "vip_auctions" in up.message.sent[-1]
    assert "mega_auctions" in up.message.sent[-1]

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "quality", "vip")))
    assert "vip_auctions" in up.message.sent[-1]
    assert "mega_auctions" not in up.message.sent[-1]

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "quality", "mega")))
    assert "mega_auctions" in up.message.sent[-1]


def test_admin_auctions_quality_invalid_and_non_admin(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "quality", "fonte_invalida")))
    assert up.message.sent[-1] == "Source de leilão não suportada. Use: vip|mega|win|sodre|superbid|copart"

    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: False)
    up2 = _Update(chat_id=1)
    asyncio.run(handlers_admin.cmd_admin(up2, _ctx("auctions", "quality")))
    assert "Sem permissão" in up2.message.sent[-1]


def test_admin_auctions_source_history_command(monkeypatch, db):
    from app.models.source_run import SourceRun

    db.add(
        SourceRun(
            source="win_auctions",
            kind="manual",
            status="success",
            payload={
                "auction_summary": {
                    "found": 20,
                    "updated": 8,
                    "errors": 0,
                    "car_lots": 20,
                    "with_current_bid_count": 8,
                    "with_auction_start_at_count": 20,
                    "with_auction_end_at_count": 0,
                    "score": 80,
                }
            },
        )
    )
    db.commit()
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "source-history", "win")))
    text = up.message.sent[-1]
    assert "Admin Leilões — monitor win_auctions" in text
    assert "encontrados=20" in text
    assert "score=80" in text


def test_admin_auctions_source_history_shows_error_cycle(monkeypatch, db):
    from app.models.source_run import SourceRun

    db.add(
        SourceRun(
            source="win_auctions",
            kind="manual",
            status="error",
            error="RuntimeError: fetch failed",
            payload={"auction_summary": {"found": 0, "inserted": 0, "updated": 0, "ignored": 0, "errors": 1, "car_lots": 0, "with_current_bid_count": 0, "with_auction_start_at_count": 0, "with_auction_end_at_count": 0, "error_type": "RuntimeError"}},
        )
    )
    db.commit()
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "source-history", "win")))
    text = up.message.sent[-1]
    assert "erros=1" in text


def test_admin_auctions_help_uses_registry_sources_hint(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "acao_invalida")))
    assert "vip|mega|win|sodre|superbid|copart" in up.message.sent[-1]
    assert "/admin auctions match [vip|mega|win|sodre|superbid|copart|wishlist <wishlist_id|index> [--force] [--all-sources]]" in up.message.sent[-1]


def test_admin_auctions_wishlist_toggle_and_match_force(monkeypatch, db):
    from app.models.user import User
    from app.models.wishlist import Wishlist

    u = User(id=uuid.uuid4(), telegram_chat_id=902, username="y")
    db.add(u)
    db.flush()
    w = Wishlist(user_id=u.id, query="gol", is_active=True, include_auctions=False)
    db.add(w)
    db.flush()
    upsert_lot(db, {"source": "vip_auctions", "external_id": "tg1", "title": "VW Gol", "status": "open"})
    db.commit()

    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    up = _Update()

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "match", "wishlist", str(w.id))))
    assert "não está habilitada para leilões" in up.message.sent[-1]

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "match", "wishlist", str(w.id), "--force")))
    assert "🎯 Busca: gol" in up.message.sent[-1] or "Sem leilões compatíveis" in up.message.sent[-1]

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "wishlist", str(w.id), "enable")))
    assert up.message.sent[-1] == "✅ Leilões ativados para esta busca."

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "wishlist", str(w.id), "disable")))
    assert up.message.sent[-1] == "✅ Leilões desativados para esta busca."


def test_admin_auctions_wishlist_toggle_not_found(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "wishlist", "invalido", "enable")))
    assert up.message.sent[-1] == "Wishlist não encontrada."


def test_render_auction_alert_preview_contract():
    from app.bot.renderers import render_auction_alert_preview

    m = types.SimpleNamespace(
        source="vip_auctions",
        title="Honda Civic SI - 2015",
        wishlist_query="civic si 2015",
        status="open",
        current_bid=91000,
        initial_bid=None,
        total_bids=8,
        year=2015,
        mileage_km=98000,
        city="São Paulo",
        state="SP",
        auction_end_at=datetime(2026, 5, 20, 18, 0, tzinfo=timezone.utc),
        reasons=["ano compatível"],
        url="https://example/lote",
    )
    text = render_auction_alert_preview(m)
    assert "Atenção:" in text
    assert "Lance atual: R$ 91.000,00" in text
    assert "Fonte: VIP Leilões" in text
    assert "Oportunidade em leilão" in text
    assert "Lance inicial:" not in text
    assert "Lance não é preço final" in text
    assert "edital" in text.lower()
    assert ("taxas" in text.lower()) or ("comissão" in text.lower())
    assert "None" not in text
    assert "Encerra:" in text
    assert "Local: São Paulo/SP" in text
    assert "Ano/KM: 2015/98.000" in text
    assert "https://example/lote" not in text


def test_admin_auctions_preview_variants(monkeypatch, db):
    from app.models.user import User
    from app.models.wishlist import Wishlist

    u = User(id=uuid.uuid4(), telegram_chat_id=902, username="z")
    db.add(u)
    db.flush()
    w_on = Wishlist(user_id=u.id, query="civic 2015", is_active=True, include_auctions=True)
    w_off = Wishlist(user_id=u.id, query="civic 2015", is_active=True, include_auctions=False)
    db.add_all([w_on, w_off])
    upsert_lot(db, {"source": "vip_auctions", "external_id": "pv1", "title": "Honda Civic 2015", "year": 2015, "status": "open", "current_bid": 91000, "url": "https://vip/pv1"})
    db.commit()

    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    up = _Update()

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "preview")))
    assert any("Preview — alerta de leilão" in s for s in up.message.sent)

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "preview", "vip")))
    assert any("Fonte: VIP Leilões" in s for s in up.message.sent)

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "preview", "wishlist", str(w_off.id))))
    assert "não está habilitada" in up.message.sent[-1]

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "preview", "wishlist", str(w_off.id), "--force")))
    assert any("Preview — alerta de leilão" in s for s in up.message.sent)


def test_admin_auctions_preview_invalid_source_and_not_found(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    up = _Update()

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "preview", "invalida")))
    assert "não suportada" in up.message.sent[-1]

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "preview", "wishlist", str(uuid.uuid4()))))
    assert up.message.sent[-1] == "Wishlist não encontrada."

def test_render_auction_alert_contract_real():
    from app.bot.renderers import render_auction_alert
    m = types.SimpleNamespace(source="vip_auctions", title="Civic", wishlist_query="civic", status="open", current_bid=100, initial_bid=90, total_bids=1, year=2015, mileage_km=1000, city="SP", state="SP", auction_end_at=datetime(2026, 5, 20, 18, 0, tzinfo=timezone.utc), reasons=["ok"], url="https://example/lote")
    text = render_auction_alert(m)
    assert "Preview" not in text
    assert "Lance não é preço final" in text
    assert "Oportunidade em leilão encontrada" in text
    assert "Lance atual" in text and "Lance inicial" in text
    assert "https://example/lote" not in text


def test_render_auction_alert_initial_bid_without_current_bid():
    from app.bot.renderers import render_auction_alert
    m = types.SimpleNamespace(source="vip_auctions", title="Civic", wishlist_query="civic", status="open", current_bid=None, initial_bid=90, total_bids=1, year=2015, mileage_km=1000, city="SP", state="SP", auction_end_at=datetime(2026, 5, 20, 18, 0, tzinfo=timezone.utc), reasons=["ok"], url="https://example/lote")
    text = render_auction_alert(m)
    assert "Lance atual:" not in text
    assert "Lance inicial: R$ 90,00" in text


def test_admin_auctions_notify_variants(monkeypatch, db):
    from app.models.user import User
    from app.models.wishlist import Wishlist
    u = User(id=uuid.uuid4(), telegram_chat_id=909, username="n")
    db.add(u); db.flush()
    w = Wishlist(user_id=u.id, query="civic 2015", is_active=True, include_auctions=True)
    db.add(w); db.flush()
    upsert_lot(db, {"source": "vip_auctions", "external_id": "n1", "title": "Honda Civic 2015", "year": 2015, "status": "open", "current_bid": 95000, "url": "https://vip/n1"})
    db.commit()

    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    up = _Update()
    up.get_bot = lambda: types.SimpleNamespace(send_message=(lambda **kwargs: asyncio.sleep(0)))

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "notify", "wishlist", str(w.id))))
    assert any("Dry-run: nenhum alerta foi enviado." in msg for msg in up.message.sent)
    assert "Dry-run: nenhum alerta foi enviado. Para enviar de verdade, rode com --confirm." in up.message.sent[-1]

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "notify", "wishlist", str(w.id), "--source", "vip", "--limit", "2", "--confirm")))
    assert "Alertas enviados" in up.message.sent[-1]

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "notify", "wishlist", str(w.id), "vip")))
    assert "Dry-run: nenhum alerta foi enviado. Para enviar de verdade, rode com --confirm." in up.message.sent[-1]

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "notify", "wishlist", str(w.id), "--source", "foo")))
    assert "não suportada" in up.message.sent[-1]

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "notify", "wishlist", str(w.id), "--limit", "9")))
    assert "Limite inválido" in up.message.sent[-1]


def test_admin_auctions_notify_non_admin_and_force(monkeypatch, db):
    from app.models.user import User
    from app.models.wishlist import Wishlist
    u = User(id=uuid.uuid4(), telegram_chat_id=910, username="n2")
    db.add(u); db.flush()
    w = Wishlist(user_id=u.id, query="gol", is_active=True, include_auctions=False)
    db.add(w); db.flush()
    upsert_lot(db, {"source": "vip_auctions", "external_id": "n2", "title": "VW Gol", "status": "open", "url": "https://vip/n2"})
    db.commit()
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))

    up = _Update(chat_id=10)
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: False)
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "notify", "wishlist", str(w.id))))
    assert "Sem permissão" in up.message.sent[-1]

    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    up.get_bot = lambda: types.SimpleNamespace(send_message=(lambda **kwargs: asyncio.sleep(0)))
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "notify", "wishlist", str(w.id))))
    assert "não está habilitada" in up.message.sent[-1]
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "notify", "wishlist", str(w.id), "--force")))
    assert "Dry-run: nenhum alerta foi enviado. Para enviar de verdade, rode com --confirm." in up.message.sent[-1]
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "notify", "wishlist", str(w.id), "--force", "--confirm")))
    assert "Alertas enviados" in up.message.sent[-1]


def test_admin_auctions_wishlists_list_and_filter_and_index_resolution(monkeypatch, db):
    from app.models.user import User
    from app.models.wishlist import Wishlist
    from app.services.wishlists_service import add_filter

    owner = User(id=uuid.uuid4(), telegram_chat_id=777, username="owner")
    other = User(id=uuid.uuid4(), telegram_chat_id=778, username="other")
    db.add_all([owner, other]); db.flush()
    w1 = Wishlist(user_id=owner.id, query="civic si", is_active=True, include_auctions=False)
    w2 = Wishlist(user_id=owner.id, query="song pro gs dm", is_active=True, include_auctions=False)
    w_other = Wishlist(user_id=other.id, query="a4 avant", is_active=True, include_auctions=False)
    db.add_all([w1, w2, w_other]); db.flush()
    add_filter(db, w1.id, "year", "gte", "2014")
    add_filter(db, w1.id, "year", "lte", "2015")
    db.commit()

    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    up = _Update(chat_id=777)

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "wishlists")))
    text = up.message.sent[-1]
    assert "Admin Leilões — buscas" in text
    assert str(w1.id) in text and str(w2.id) in text
    assert "Ano entre 2014 e 2015" in text
    assert "Leilões: desativado" in text

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "wishlists", "song")))
    assert "song pro gs dm" in up.message.sent[-1].lower()
    assert "civic si" not in up.message.sent[-1].lower()

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "wishlist", "1", "enable")))
    db.refresh(w1)
    assert up.message.sent[-1] == "✅ Leilões ativados para esta busca."
    assert w1.include_auctions is True

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "wishlist", "1", "disable")))
    db.refresh(w1)
    assert up.message.sent[-1] == "✅ Leilões desativados para esta busca."
    assert w1.include_auctions is False

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "wishlist", "3", "enable")))
    assert up.message.sent[-1] == "Busca não encontrada para este índice. Use /admin auctions wishlists para ver IDs e índices."


def test_admin_auctions_match_preview_notify_accept_index_and_do_not_cross_user(monkeypatch, db):
    from app.models.user import User
    from app.models.wishlist import Wishlist

    owner = User(id=uuid.uuid4(), telegram_chat_id=880, username="o")
    other = User(id=uuid.uuid4(), telegram_chat_id=881, username="p")
    db.add_all([owner, other]); db.flush()
    w1 = Wishlist(user_id=owner.id, query="gol", is_active=True, include_auctions=True)
    w_other = Wishlist(user_id=other.id, query="civic", is_active=True, include_auctions=True)
    db.add_all([w1, w_other]); db.flush()
    upsert_lot(db, {"source": "vip_auctions", "external_id": "idx1", "title": "VW Gol", "status": "open", "url": "https://vip/idx1"})
    db.commit()

    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    up = _Update(chat_id=880)
    up.get_bot = lambda: types.SimpleNamespace(send_message=(lambda **kwargs: asyncio.sleep(0)))

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "match", "wishlist", "1", "--force")))
    assert "🎯 Busca: gol" in up.message.sent[-1] or "Sem leilões compatíveis" in up.message.sent[-1]

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "preview", "wishlist", "1", "--force")))
    assert any("Preview — alerta de leilão" in s for s in up.message.sent)

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "notify", "wishlist", "1")))
    assert "Dry-run: nenhum alerta foi enviado. Para enviar de verdade, rode com --confirm." in up.message.sent[-1]

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "match", "wishlist", str(w1.id), "--force")))
    assert "🎯 Busca: gol" in up.message.sent[-1] or "Sem leilões compatíveis" in up.message.sent[-1]

    up_other = _Update(chat_id=880)
    asyncio.run(handlers_admin.cmd_admin(up_other, _ctx("auctions", "wishlist", "2", "enable")))
    assert up_other.message.sent[-1] == "Busca não encontrada para este índice. Use /admin auctions wishlists para ver IDs e índices."


def test_admin_auctions_match_wishlist_debug_shows_recent_candidates_without_matches(monkeypatch, db):
    from app.models.user import User
    from app.models.wishlist import Wishlist

    owner = User(id=uuid.uuid4(), telegram_chat_id=990, username="dbg")
    db.add(owner); db.flush()
    w1 = Wishlist(user_id=owner.id, query="gol", is_active=True, include_auctions=True)
    db.add(w1); db.commit()
    from app.models.wishlist_filter import WishlistFilter
    db.add_all([
        WishlistFilter(wishlist_id=w1.id, field="year", operator="gte", value="2018"),
        WishlistFilter(wishlist_id=w1.id, field="state", operator="eq", value="SP"),
    ])
    db.commit()

    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    monkeypatch.setattr(handlers_admin, "match_auction_lots_for_wishlist", lambda *_a, **_k: [])
    monkeypatch.setattr(
        handlers_admin,
        "debug_auction_lot_candidates_for_wishlist",
        lambda *_a, **_k: [
            {"title": "Gol 1.0", "source": "vip_auctions", "item_type": "car", "year": 2019, "current_bid": 10000, "updated_at": "2026-05-17T00:00:00+00:00", "passes_filters": False, "score": 0, "reject_reason": "filters_not_matched"},
            {"title": "Gol Track", "source": "vip_auctions", "item_type": "car", "year": 2020, "current_bid": 12000, "updated_at": "2026-05-17T01:00:00+00:00", "passes_filters": True, "score": 0, "reject_reason": "text_score_zero"},
        ],
    )
    up = _Update(chat_id=990)
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "match", "wishlist", "1", "--debug")))
    msg = up.message.sent[-1]
    assert "Filtros:" in msg
    assert "Ano" in msg or "Estado: SP" in msg
    assert "Candidatos recentes:" in msg
    assert "motivo=filters_not_matched" in msg
    assert "motivo=text_score_zero" in msg


def test_admin_auctions_notify_lock_guard(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    up = _Update()

    async def _run():
        await handlers_admin._ADMIN_AUCTION_NOTIFY_LOCK.acquire()
        try:
            await handlers_admin.cmd_admin(up, _ctx("auctions", "notify", "wishlist", str(uuid.uuid4())))
        finally:
            handlers_admin._ADMIN_AUCTION_NOTIFY_LOCK.release()

    asyncio.run(_run())
    assert up.message.sent[-1] == "Já existe um envio de alerta de leilão em andamento. Aguarde finalizar."


def test_admin_auctions_notify_error_shows_summary(monkeypatch, db):
    from app.models.user import User
    from app.models.wishlist import Wishlist

    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    up = _Update()
    up.get_bot = lambda: types.SimpleNamespace(send_message=(lambda **kwargs: asyncio.sleep(0)))
    u = User(id=uuid.uuid4(), telegram_chat_id=999, username="err")
    db.add(u); db.flush()
    w = Wishlist(user_id=u.id, query="uno", is_active=True, include_auctions=True)
    db.add(w); db.commit()

    async def _fake_send(*_args, **_kwargs):
        return {
            "sent": 0,
            "skipped_duplicate": 0,
            "skipped_no_match": 0,
            "skipped_missing_chat_id": 0,
            "errors": 1,
            "messages": ["Falha ao enviar alerta: timeout"],
        }

    monkeypatch.setattr(handlers_admin, "send_auction_notifications_for_wishlist", _fake_send)
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "notify", "wishlist", str(w.id), "--confirm")))
    assert "Erros: 1" in up.message.sent[-1]
    assert "Detalhe: Falha ao enviar alerta: timeout" in up.message.sent[-1]


def test_admin_auctions_notify_dry_run_never_sends(monkeypatch, db):
    from app.models.user import User
    from app.models.wishlist import Wishlist
    u = User(id=uuid.uuid4(), telegram_chat_id=999, username="dry")
    db.add(u); db.flush()
    w = Wishlist(user_id=u.id, query="civic 2015", is_active=True, include_auctions=True)
    db.add(w); db.flush()
    upsert_lot(db, {"source": "vip_auctions", "external_id": "dry2", "title": "Honda Civic 2015", "year": 2015, "status": "open", "url": "https://vip/dry2"})
    db.commit()
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    up = _Update()
    called = {"send": 0}

    async def _fake_send(*_args, **_kwargs):
        called["send"] += 1
        return {"sent": 0, "skipped_duplicate": 0, "skipped_no_match": 0, "skipped_missing_chat_id": 0, "errors": 0, "messages": []}

    monkeypatch.setattr(handlers_admin, "send_auction_notifications_for_wishlist", _fake_send)
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "notify", "wishlist", str(w.id))))
    assert called["send"] == 0


def test_admin_auctions_notify_experimental_requires_allow(monkeypatch, db):
    from app.models.user import User
    from app.models.wishlist import Wishlist
    u = User(id=uuid.uuid4(), telegram_chat_id=911, username="exp")
    db.add(u); db.flush()
    w = Wishlist(user_id=u.id, query="civic 2015", is_active=True, include_auctions=True)
    db.add(w); db.flush()
    upsert_lot(db, {"source": "mega_auctions", "external_id": "exp1", "title": "Honda Civic 2015", "year": 2015, "status": "open", "url": "https://mega/exp1"})
    db.commit()
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    up = _Update()
    up.get_bot = lambda: types.SimpleNamespace(send_message=(lambda **kwargs: asyncio.sleep(0)))

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "notify", "wishlist", str(w.id), "--source", "mega")))
    assert "Source não elegível" in up.message.sent[-1]

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "notify", "wishlist", str(w.id), "--source", "mega", "--allow-experimental")))
    assert "Dry-run: nenhum alerta foi enviado. Para enviar de verdade, rode com --confirm." in up.message.sent[-1]


def test_admin_auctions_notify_allow_experimental_requires_source(monkeypatch, db):
    from app.models.user import User
    from app.models.wishlist import Wishlist

    u = User(id=uuid.uuid4(), telegram_chat_id=912, username="exp2")
    db.add(u); db.flush()
    w = Wishlist(user_id=u.id, query="civic 2015", is_active=True, include_auctions=True)
    db.add(w); db.flush()
    upsert_lot(db, {"source": "vip_auctions", "external_id": "exp2-v1", "title": "Honda Civic 2015", "year": 2015, "status": "open", "url": "https://vip/exp2-v1"})
    upsert_lot(db, {"source": "mega_auctions", "external_id": "exp2-m1", "title": "Honda Civic 2015", "year": 2015, "status": "open", "url": "https://mega/exp2-m1"})
    db.commit()

    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))

    sent_calls = {"n": 0}
    class _Bot:
        async def send_message(self, **_kwargs):
            sent_calls["n"] += 1

    up = _Update()
    up.get_bot = lambda: _Bot()
    before_appkv = db.query(AppKV).count()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "notify", "wishlist", str(w.id), "--allow-experimental", "--confirm")))
    assert up.message.sent[-1] == "Use --source <alias> junto com --allow-experimental para evitar envio amplo por fontes experimentais."
    assert sent_calls["n"] == 0
    assert db.query(AppKV).count() == before_appkv


def test_admin_notify_allow_no_bid_variants(monkeypatch, db):
    from app.models.user import User
    from app.models.wishlist import Wishlist
    u = User(id=uuid.uuid4(), telegram_chat_id=913, username="allow")
    db.add(u); db.flush()
    w = Wishlist(user_id=u.id, query="honda civic", is_active=True, include_auctions=True)
    db.add(w); db.flush()
    upsert_lot(db, {"source": "vip_auctions", "external_id": "anb1", "title": "Honda Civic", "status": "open", "url": "https://vip/anb1"})
    db.commit()
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    up = _Update()

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "notify", "wishlist", str(w.id), "--source", "vip")))
    assert "nenhum match com lance atual ou lance inicial" in up.message.sent[-1]

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "notify", "wishlist", str(w.id), "--source", "vip", "--allow-no-bid")))
    assert "Dry-run: nenhum alerta foi enviado. Para enviar de verdade, rode com --confirm." in up.message.sent[-1]

def test_admin_auctions_sources_and_toggles(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "sources")))
    assert "vip_auctions" in up.message.sent[-1]

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "source-config", "mega", "disable")))
    assert "source=mega_auctions" in up.message.sent[-1]

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "source-config", "mega", "user-enable")))
    assert "Não é possível user-enable" in up.message.sent[-1]


def test_admin_auctions_sources_renders_reconciled_metadata_status(monkeypatch, db):
    db.add(SourceConfig(source="vip_auctions", source_type="auction", is_enabled=False, user_eligible=False, status="active", extra={"allowed_item_types": ["car", "motorcycle"]}))
    db.add(SourceConfig(source="win_auctions", source_type="auction", is_enabled=True, user_eligible=False, status="experimental"))
    db.add(SourceConfig(source="superbid_auctions", source_type="auction", is_enabled=True, user_eligible=False, status="experimental"))
    db.add(SourceConfig(source="copart_auctions", source_type="auction", is_enabled=False, user_eligible=False, status="needs_js_or_endpoint_study"))
    db.add(SourceConfig(source="sodre_auctions", source_type="auction", is_enabled=False, user_eligible=False, status="needs_study"))
    db.commit()
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))

    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "sources")))
    text = up.message.sent[-1]

    assert "VIP Leilões" in text
    assert "source: vip_auctions" in text
    assert "status: production_ready" in text
    assert "source: win_auctions" in text and "status: experimental_functional_vehicle" in text
    assert "source: superbid_auctions" in text and "status: needs_study" in text
    assert "source: copart_auctions" in text and "status: needs_study" in text
    assert "source: sodre_auctions" in text and "status: blocked/needs_study" in text
    vip = db.query(SourceConfig).filter(SourceConfig.source == "vip_auctions").one()
    assert vip.is_enabled is False
    assert vip.user_eligible is False
    assert vip.extra == {"allowed_item_types": ["car", "motorcycle"]}


def test_admin_auctions_quality_matches_readiness_window_for_vip_48h(monkeypatch, db):
    from app.services.app_kv_service import set_kv

    now = datetime.now(timezone.utc)
    upsert_lot(
        db,
        {
            "source": "vip_auctions",
            "external_id": "vip-30h-admin",
            "title": "Honda Civic",
            "item_type": "car",
            "year": 2020,
            "current_bid": 50000,
            "url": "https://vip/30h-admin",
            "status": "open",
        },
    )
    lot = db.query(AuctionLot).filter_by(source="vip_auctions", external_id="vip-30h-admin").one()
    lot.updated_at = now - timedelta(hours=30)
    db.add(SourceConfig(source="vip_auctions", source_type="auction", is_enabled=True, user_eligible=True, status="active", extra={"allowed_item_types": ["car"]}))
    set_kv(db, "auction_notification_settings", {"max_lot_age_hours": 48})
    db.commit()
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))

    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "quality", "vip")))
    quality_text = up.message.sent[-1]
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "readiness")))
    readiness_text = up.message.sent[-1]

    assert "Atualizados 24h: 0" in quality_text
    assert "Qualidade dados car: sim" in quality_text
    assert "Pronta user-facing car: sim" in quality_text
    assert "Janela piloto car: 48h" in quality_text
    assert "vip_auctions: car_lots=1" in readiness_text
    assert "dados_car=sim" in readiness_text
    assert "user_facing=sim" in readiness_text


def test_admin_source_unified_auction_enable_disable_and_categories(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    up = _Update()

    cfg = db.query(SourceConfig).filter(SourceConfig.source == "vip_auctions").first()
    if cfg:
        db.delete(cfg); db.commit()

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("source", "vip", "enable")))
    assert "source=vip_auctions enabled=sim" in up.message.sent[-1]
    cfg = db.query(SourceConfig).filter(SourceConfig.source == "vip_auctions").first()
    assert cfg is not None and bool(cfg.is_enabled) is True

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("source", "vip", "disable")))
    cfg = db.query(SourceConfig).filter(SourceConfig.source == "vip_auctions").first()
    assert "source=vip_auctions enabled=não" in up.message.sent[-1]
    assert bool(cfg.is_enabled) is False and bool(cfg.user_eligible) is False

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("source", "vip", "user-enable")))
    assert "Não é possível user-enable com source disabled." in up.message.sent[-1]

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("source", "vip", "categories")))
    assert "categorias=car" in up.message.sent[-1]

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("source", "vip", "categories", "set", "car,motorcycle")))
    cfg = db.query(SourceConfig).filter(SourceConfig.source == "vip_auctions").first()
    assert sorted((cfg.extra or {}).get("allowed_item_types") or []) == ["car", "motorcycle"]

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "source-config", "vip", "categories", "set", "car,motorcycle")))
    cfg = db.query(SourceConfig).filter(SourceConfig.source == "vip_auctions").first()
    assert sorted((cfg.extra or {}).get("allowed_item_types") or []) == ["car", "motorcycle"]

def test_admin_auctions_notify_run_default_dry_run(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))

    async def _fake_job(*_a, **kwargs):
        assert kwargs["dry_run"] is True
        return {"wishlists_scanned": 5, "wishlists_with_matches": 2, "previews": 2, "sent": 0, "skipped_duplicate": 1, "skipped_no_match": 3, "skipped_missing_chat_id": 0, "skipped_daily_limit": 0, "skipped_score_below_min": 1, "skipped_stale_lot": 2, "skipped_missing_lot_updated_at": 0, "errors": 0}

    monkeypatch.setattr(handlers_admin, "run_auction_notification_job", _fake_job)
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "notify-run")))
    assert "Modo: dry-run" in up.message.sent[-1]


def test_admin_auctions_notify_run_real(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))

    async def _fake_job(*_a, **kwargs):
        assert kwargs["dry_run"] is False
        return {"wishlists_scanned": 1, "wishlists_with_matches": 1, "previews": 0, "sent": 1, "skipped_duplicate": 0, "skipped_no_match": 0, "skipped_missing_chat_id": 0, "skipped_daily_limit": 0, "skipped_score_below_min": 1, "skipped_stale_lot": 2, "skipped_missing_lot_updated_at": 0, "errors": 0}

    monkeypatch.setattr(handlers_admin, "run_auction_notification_job", _fake_job)
    set_kv(db, "auction_notification_settings", {"dry_run": True})
    user = User(id=uuid.uuid4(), telegram_chat_id=999)
    db.add(user)
    db.flush()
    db.add(Wishlist(user_id=user.id, query="touareg", is_active=True, include_auctions=True))
    db.commit()
    up = _Update()
    monkeypatch.setattr(handlers_admin, "build_auction_notification_readiness", lambda _db: {"summary": {"car_pilot_ready_sources": ["vip_auctions"]}})
    monkeypatch.setattr(handlers_admin, "is_auction_source_enabled", lambda _db, _src: True)
    monkeypatch.setattr(handlers_admin, "is_auction_source_user_eligible", lambda _db, _src: True)
    monkeypatch.setattr(handlers_admin, "get_auction_allowed_item_types", lambda _db, _src: {"car"})
    up = _Update()
    up.get_bot = lambda: object()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "notify-run", "--source", "vip", "--real")))
    assert "envio real manual" in up.message.sent[-1]
    assert "Enviados: 1" in up.message.sent[-1]
    cfg = handlers_admin.get_auction_notification_runtime_settings(db)
    assert cfg["dry_run"] is True
    db.expire_all()
    row = (
        db.query(SystemLog)
        .filter(SystemLog.component == "bot.admin", SystemLog.message == "auction_notification_manual_real_run_finished")
        .order_by(SystemLog.created_at.desc())
        .first()
    )
    assert row is not None




def test_admin_auctions_notify_run_real_readiness_summary_allows_run(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))

    called = {"ran": False}

    async def _fake_job(*_a, **kwargs):
        called["ran"] = True
        assert kwargs["dry_run"] is False
        return {"wishlists_scanned": 1, "wishlists_with_matches": 1, "previews": 0, "sent": 1, "skipped_duplicate": 0, "skipped_no_match": 0, "skipped_missing_chat_id": 0, "skipped_daily_limit": 0, "skipped_score_below_min": 0, "skipped_stale_lot": 0, "skipped_missing_lot_updated_at": 0, "errors": 0}

    monkeypatch.setattr(handlers_admin, "run_auction_notification_job", _fake_job)
    user = User(id=uuid.uuid4(), telegram_chat_id=999)
    db.add(user)
    db.flush()
    db.add(Wishlist(user_id=user.id, query="touareg", is_active=True, include_auctions=True))
    db.commit()
    monkeypatch.setattr(handlers_admin, "build_auction_notification_readiness", lambda _db: {"summary": {"car_pilot_ready_sources": ["vip_auctions"]}})
    monkeypatch.setattr(handlers_admin, "is_auction_source_enabled", lambda _db, _src: True)
    monkeypatch.setattr(handlers_admin, "is_auction_source_user_eligible", lambda _db, _src: True)
    monkeypatch.setattr(handlers_admin, "get_auction_allowed_item_types", lambda _db, _src: {"car"})
    up = _Update()
    up.get_bot = lambda: object()

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "notify-run", "--source", "vip", "--real")))

    assert called["ran"] is True
    assert "readiness_sem_source_pronta" not in "\n".join(up.message.sent)

def test_admin_auctions_notify_run_real_without_source_blocked(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "notify-run", "--real")))
    assert "exige source explícita" in up.message.sent[-1]


def test_admin_auctions_notify_run_real_guardrail_failure_persists_log(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    user = User(id=uuid.uuid4(), telegram_chat_id=999)
    db.add(user)
    db.flush()
    db.add(Wishlist(user_id=user.id, query="touareg", is_active=True, include_auctions=True))
    db.commit()
    monkeypatch.setattr(handlers_admin, "build_auction_notification_readiness", lambda _db: {"summary": {"car_pilot_ready_sources": []}})
    monkeypatch.setattr(handlers_admin, "is_auction_source_user_eligible", lambda _db, _src: True)
    up = _Update()
    up.get_bot = lambda: object()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "notify-run", "--source", "vip", "--real")))
    assert "Falha operacional no envio real manual" in up.message.sent[-1]
    db.expire_all()
    row = (
        db.query(SystemLog)
        .filter(SystemLog.component == "bot.admin", SystemLog.message == "auction_notification_manual_real_run_failed")
        .order_by(SystemLog.created_at.desc())
        .first()
    )
    assert row is not None


def test_admin_auctions_notify_run_real_non_vip_blocked(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    monkeypatch.setattr(handlers_admin, "is_auction_source_user_eligible", lambda _db, _src: True)
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "notify-run", "--source", "mega", "--real")))
    assert "apenas para vip_auctions" in up.message.sent[-1]


def test_admin_auctions_notify_run_renders_rejections(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))

    async def _fake_job(*_a, **kwargs):
        assert kwargs["dry_run"] is True
        return {"wishlists_scanned": 1, "wishlists_with_matches": 0, "previews": 0, "sent": 0, "skipped_duplicate": 0, "skipped_no_match": 1, "skipped_missing_chat_id": 0, "skipped_daily_limit": 0, "skipped_score_below_min": 0, "skipped_stale_lot": 1, "skipped_missing_lot_updated_at": 0, "errors": 0, "rejections": [{"reason": "stale_lot", "title": "Lote X", "detail": "updated_at fora da janela 48h"}]}

    monkeypatch.setattr(handlers_admin, "run_auction_notification_job", _fake_job)
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "notify-run")))
    assert "Rejeições principais:" in up.message.sent[-1]
    assert "stale_lot: Lote X" in up.message.sent[-1]


def test_admin_auctions_notify_run_lock_guard(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    called = {"job": 0}

    async def _fake_job(*_a, **_k):
        called["job"] += 1
        return {"wishlists_scanned": 0, "wishlists_with_matches": 0, "previews": 0, "sent": 0, "skipped_duplicate": 0, "skipped_no_match": 0, "skipped_missing_chat_id": 0, "skipped_daily_limit": 0, "skipped_score_below_min": 1, "skipped_stale_lot": 2, "skipped_missing_lot_updated_at": 0, "errors": 0}

    monkeypatch.setattr(handlers_admin, "run_auction_notification_job", _fake_job)
    up = _Update()

    async def _run_locked():
        await handlers_admin._ADMIN_AUCTION_NOTIFY_LOCK.acquire()
        try:
            await handlers_admin.cmd_admin(up, _ctx("auctions", "notify-run"))
        finally:
            handlers_admin._ADMIN_AUCTION_NOTIFY_LOCK.release()

    asyncio.run(_run_locked())
    assert "Já existe uma execução de notify-run de leilões em andamento. Aguarde finalizar." in up.message.sent[-1]
    assert called["job"] == 0


def test_admin_auctions_notify_status_variants(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    monkeypatch.setattr(
        handlers_admin,
        "build_auction_notification_status",
        lambda _db: {
            "enabled": False,
            "dry_run": True,
            "scheduler_minutes": 60,
            "max_wishlists": 20,
            "max_per_wishlist": 1,
            "max_per_user_per_day": 3,
            "eligible_sources": ["vip_auctions"],
            "last_run_at": "-",
            "last_status": "unknown",
            "last_reason": "-",
            "last_sent": 0,
            "last_previews": 0,
            "last_skipped_no_match": 0,
            "last_skipped_duplicate": 0,
            "last_skipped_daily_limit": 0,
            "last_skipped_score_below_min": 1, "last_skipped_stale_lot": 2, "last_skipped_missing_lot_updated_at": 0, "last_errors": 0,
        },
    )
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "notify-status")))
    assert "Envio automático desligado. Seguro para produção." in up.message.sent[-1]
    assert "- scheduler automático: desligado" in up.message.sent[-1]
    assert "/admin auctions notify-samples" in up.message.sent[-1]
    assert "Sources elegíveis:" in up.message.sent[-1]
    assert "- vip_auctions" in up.message.sent[-1]

    monkeypatch.setattr(
        handlers_admin,
        "build_auction_notification_status",
        lambda _db: {"enabled": True, "dry_run": True, "scheduler_minutes": 60, "max_wishlists": 20, "max_per_wishlist": 1, "max_per_user_per_day": 3, "eligible_sources": ["vip_auctions"], "last_run_at": "2026-05-16 17:45 UTC", "last_status": "dry_run", "last_reason": "-", "last_sent": 0, "last_previews": 1, "last_skipped_no_match": 0, "last_skipped_duplicate": 0, "last_skipped_daily_limit": 0, "last_errors": 0},
    )
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "notify-status")))
    assert "Scheduler automático em simulação. Nenhum alerta real é enviado automaticamente." in up.message.sent[-1]
    assert "- scheduler automático: dry-run" in up.message.sent[-1]

    monkeypatch.setattr(
        handlers_admin,
        "build_auction_notification_status",
        lambda _db: {"enabled": True, "dry_run": False, "scheduler_minutes": 60, "max_wishlists": 20, "max_per_wishlist": 1, "max_per_user_per_day": 3, "eligible_sources": ["vip_auctions"], "last_run_at": "2026-05-16 17:45 UTC", "last_status": "sent", "last_reason": "-", "last_sent": 1, "last_previews": 0, "last_skipped_no_match": 0, "last_skipped_duplicate": 0, "last_skipped_daily_limit": 0, "last_errors": 0},
    )
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "notify-status")))
    assert "🚨 Envio automático real ativo" in up.message.sent[-1]
    assert "- scheduler automático: envio real automático" in up.message.sent[-1]


def test_admin_auctions_notify_status_non_admin(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: False)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    called = {"status": 0}

    def _status(_db):
        called["status"] += 1
        return {}

    monkeypatch.setattr(handlers_admin, "build_auction_notification_status", _status)
    up = _Update(chat_id=111)
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "notify-status")))
    assert "Sem permissão" in up.message.sent[-1]
    assert called["status"] == 0


def test_admin_auctions_digest_renders_and_is_read_only(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    called = {"notify": 0}

    async def _notify(*_a, **_k):
        called["notify"] += 1
        return {}

    monkeypatch.setattr(handlers_admin, "run_auction_notification_job", _notify)
    monkeypatch.setattr(
        handlers_admin,
        "build_auction_dry_run_digest",
        lambda _db, hours=24: {
            "window_hours": hours,
            "since": "2026-05-17T01:00:00+00:00",
            "last_run_at": "2026-05-18T01:42:00+00:00",
            "last_status": "dry_run",
            "runs": 3,
            "wishlists_scanned": 6,
            "wishlists_with_matches": 2,
            "previews": 2,
            "sent": 0,
            "errors": 0,
            "skips": {"stale_lot": 1, "no_match": 8, "score_below_min": 0, "item_type_not_allowed": 0, "duplicate": 0, "daily_limit": 0},
            "source_summary": {"vip_auctions": {"previews": 2, "errors": 0}},
            "latest_samples": [{"wishlist_query": "touareg", "title": "TOUAREG", "source_label": "VIP Leilões", "score": 72, "current_bid": "10000.00"}],
            "latest_rejections": [{"wishlist_query": "song", "title": "SONG PLUS", "reason": "stale_lot", "score": 66}],
            "history_note": "Histórico parcial: usando último summary salvo para complementar counters.",
            "recommendation": {"status": "keep_dry_run", "message": "Dry-run saudável. Manter coleta por mais ciclos."},
        },
    )
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "digest")))
    msg = up.message.sent[-1]
    assert "digest dry-run 24h" in msg
    assert "buscas avaliadas: 6" in msg
    assert "lote antigo: 1" in msg
    assert "Últimas amostras:" in msg
    assert "Últimas rejeições:" in msg
    assert "Histórico parcial: usando último summary salvo para complementar counters." in msg
    assert called["notify"] == 0


def test_admin_auctions_digest_hours_and_validation_and_non_admin(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    monkeypatch.setattr(handlers_admin, "build_auction_dry_run_digest", lambda _db, hours=24: {"since": "-", "last_run_at": "-", "last_status": "unknown", "runs": 0, "wishlists_scanned": 0, "wishlists_with_matches": 0, "previews": 0, "sent": 0, "errors": 0, "skips": {}, "source_summary": {}, "latest_samples": [], "latest_rejections": [], "recommendation": {"status": "no_data", "message": "Sem dados suficientes."}})
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "digest", "--hours", "6")))
    assert "digest dry-run 6h" in up.message.sent[-1]
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "digest", "--hours", "0")))
    assert "hours inválido" in up.message.sent[-1]
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: False)
    up2 = _Update(chat_id=77)
    asyncio.run(handlers_admin.cmd_admin(up2, _ctx("auctions", "digest")))
    assert "Sem permissão" in up2.message.sent[-1]


def test_admin_auctions_notify_samples_empty(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    monkeypatch.setattr(handlers_admin, "build_auction_notification_samples", lambda _db, limit=10: {"created_at": "-", "summary": {}, "samples": []})
    called = {"job": 0}

    async def _job(*_a, **_k):
        called["job"] += 1
        return {}

    monkeypatch.setattr(handlers_admin, "run_auction_notification_job", _job)
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "notify-samples")))
    assert "Ainda não há amostras de dry-run." in up.message.sent[-1]
    assert called["job"] == 0


def test_admin_auctions_notify_samples_render(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    monkeypatch.setattr(
        handlers_admin,
        "build_auction_notification_samples",
        lambda _db, limit=10: {
            "created_at": "2026-05-16 21:10 UTC",
            "summary": {"wishlists_scanned": 5, "wishlists_with_matches": 2, "previews": 2, "skipped_duplicate": 1, "skipped_no_match": 3, "skipped_daily_limit": 0, "skipped_score_below_min": 1, "skipped_stale_lot": 2, "skipped_missing_lot_updated_at": 0, "errors": 0},
            "samples": [{"wishlist_query": "SONG PRO", "title": "SONG PLUS", "source": "vip_auctions", "score": 76, "current_bid": "91000.00", "initial_bid": "88000.00", "year": 2008, "mileage_km": 128468, "total_bids": 1, "auction_end_at": "2026-05-20T12:00:00+00:00", "location": "São Paulo/SP", "url": "https://x", "button_label": "🔗 Ver leilão"}] * 12,
        },
    )
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "notify-samples")))
    msg = up.message.sent[-1]
    assert "últimas amostras dry-run" in msg
    assert "1. Wishlist: SONG PRO" in msg
    assert "🧪 Preview — alerta de leilão" in msg
    assert "⚠️ Oportunidade em leilão encontrada" in msg
    assert "Fonte: VIP Leilões" in msg
    assert "Source: vip_auctions" not in msg
    assert "Score: 76" in msg
    assert "Score: 76.00" not in msg
    assert "Lance atual: R$ 91.000,00" in msg
    assert "Lance inicial: R$ 88.000,00" in msg
    assert "Ano/KM: 2008/128.468" in msg
    assert "Lances: 1" in msg
    assert "Encerra:" in msg
    assert "Local: São Paulo/SP" in msg
    preview_block = msg.split("🧪 Preview — alerta de leilão", 1)[1]
    preview_block = preview_block.split("Botão:", 1)[0]
    assert "Score:" not in preview_block
    assert "Lance não é preço final" in msg
    assert "edital" in msg
    assert "taxas/comissão" in msg
    assert "documentação" in msg
    assert "vistoria" in msg
    assert "Link:\nhttps://x" not in preview_block
    assert "Botão:" in msg
    assert "🔗 Ver leilão" in msg
    assert "https://x" in msg
    assert "10." in msg
    assert "11." not in msg


def test_admin_auctions_notify_samples_render_legacy_payload_no_none(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    monkeypatch.setattr(
        handlers_admin,
        "build_auction_notification_samples",
        lambda _db, limit=10: {
            "created_at": "2026-05-16 21:10 UTC",
            "summary": {"previews": 1},
            "samples": [{"wishlist_query": "touareg", "source": "vip_auctions", "score": 72, "current_bid": "10000.00", "url": "https://x"}],
        },
    )
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "notify-samples")))
    msg = up.message.sent[-1]
    assert "Sem título" in msg
    assert "None" not in msg
    assert "R$ 10.000,00" in msg

def test_admin_auctions_readiness_renders_status_and_is_read_only(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))

    called = {"job": 0}

    async def _fake_job(*_args, **_kwargs):
        called["job"] += 1
        return {}

    monkeypatch.setattr(handlers_admin, "run_auction_notification_job", _fake_job)

    baseline_kv = db.query(AppKV).count()
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "readiness")))
    text = up.message.sent[-1]
    assert "Admin Leilões — readiness" in text
    assert "Envio real automático não recomendado" in text
    assert called["job"] == 0
    assert db.query(AppKV).count() == baseline_kv


def test_admin_auctions_readiness_non_admin_blocked(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: False)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    up = _Update(chat_id=10)
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "readiness")))
    assert "Sem permissão" in up.message.sent[-1]

def test_admin_source_unified_handles_detached_after_commit(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)

    class _DetachSessionWrap(_SessionWrap):
        def __exit__(self, *_):
            try:
                self.db.expire_all()
            finally:
                self.db.close()
            return False

    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _DetachSessionWrap(db))

    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("source", "vip", "enable")))
    assert "✅ source=vip_auctions enabled=sim" in up.message.sent[-1]

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("source", "vip", "user-enable")))
    assert up.message.sent[-1] == "✅ source=vip_auctions enabled=sim user_eligible=sim"

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("source", "vip", "disable")))
    assert up.message.sent[-1] == "✅ source=vip_auctions enabled=não user_eligible=não"


def test_admin_source_legacy_and_categories_paths_still_work(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))

    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "source-config", "vip", "enable")))
    assert "✅ source=vip_auctions enabled=sim" in up.message.sent[-1]

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "source-config", "vip", "user-enable")))
    assert up.message.sent[-1] == "✅ source=vip_auctions enabled=sim user_eligible=sim"

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("source", "vip", "categories", "set", "car")))
    assert up.message.sent[-1] == "✅ source=vip_auctions enabled=sim user_eligible=sim"


def test_admin_auctions_notify_samples_render_rejections_with_string_bid(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    monkeypatch.setattr(
        handlers_admin,
        "build_auction_notification_samples",
        lambda _db, limit=10: {
            "created_at": "2026-05-16 21:10 UTC",
            "summary": {},
            "samples": [],
            "rejections": [{"wishlist_query": "Civic", "source": "vip_auctions", "title": "Honda Civic", "reason": "score_below_min", "updated_at": "2026-05-16T21:10:00+00:00", "score": 75, "current_bid": "8500.00"}],
        },
    )
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "notify-samples")))
    msg = up.message.sent[-1]
    assert "Rejeições recentes:" in msg
    assert "Motivo: score abaixo do mínimo" in msg
    assert "Lance atual: R$ 8.500,00" in msg


def test_admin_auctions_notify_samples_render_rejections_humanized_stale_lot(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    monkeypatch.setattr(
        handlers_admin,
        "build_auction_notification_samples",
        lambda _db, limit=10: {
            "created_at": "2026-05-16 21:10 UTC",
            "summary": {},
            "samples": [],
            "rejections": [{"wishlist_query": "Civic", "source": "vip_auctions", "title": "Honda Civic", "reason": "stale_lot"}],
        },
    )
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "notify-samples")))
    assert "Motivo: lote antigo" in up.message.sent[-1]


def test_admin_auctions_readiness_warns_functional_source_without_car(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    db.add(SourceConfig(source="win_auctions", source_type="auction", is_enabled=True, user_eligible=False))
    upsert_lot(db, {"source": "win_auctions", "external_id": "w-re", "item_type": "real_estate", "url": "https://win/re", "current_bid": 100000})
    lot = db.query(AuctionLot).filter_by(source="win_auctions", external_id="w-re").first()
    if lot:
        lot.updated_at = datetime.now(timezone.utc)
    db.commit()

    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "readiness")))
    text = up.message.sent[-1]
    assert "win_auctions funcional, mas sem lotes car recentes" in text
    assert "Fora do piloto de carros" in text
    assert "dados_car=não" in text
    assert "status/live=não" in text
    assert "início=não" in text
    assert "encerramento=não" in text
    assert "user_facing=não" in text


def test_admin_auctions_readiness_warns_mega_car_without_bid(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    db.add(SourceConfig(source="mega_auctions", source_type="auction", is_enabled=True, user_eligible=False))
    upsert_lot(db, {"source": "mega_auctions", "external_id": "m-car", "item_type": "car", "url": "https://mega/car", "year": 2020})
    lot = db.query(AuctionLot).filter_by(source="mega_auctions", external_id="m-car").first()
    if lot:
        lot.updated_at = datetime.now(timezone.utc)
    db.commit()

    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "readiness")))
    text = up.message.sent[-1]
    assert "mega_auctions tem carros, mas sem lance inicial/atual" in text
    assert "Manter experimental" in text
    assert "car_lots=1" in text


def test_admin_auctions_notify_samples_render_rejections_humanized_item_type_blocked(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    monkeypatch.setattr(
        handlers_admin,
        "build_auction_notification_samples",
        lambda _db, limit=10: {
            "created_at": "2026-05-16 21:10 UTC",
            "summary": {},
            "samples": [],
            "rejections": [{"wishlist_query": "SONG", "source": "vip_auctions", "title": "F700 GS", "reason": "item_type_not_allowed"}],
        },
    )
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "notify-samples")))
    assert "Motivo: tipo bloqueado" in up.message.sent[-1]
    assert "Nenhum novo alerta elegível nesta última execução." in up.message.sent[-1]
    assert "Alguns lotes foram bloqueados por categoria" in up.message.sent[-1]


def test_admin_auctions_notify_samples_rejections_duplicate_adds_operational_reading(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    monkeypatch.setattr(
        handlers_admin,
        "build_auction_notification_samples",
        lambda _db, limit=10: {"created_at": "-", "summary": {}, "samples": [], "rejections": [{"reason": "duplicate"}]},
    )
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "notify-samples")))
    assert "Nenhum novo alerta elegível nesta última execução." in up.message.sent[-1]
    assert "já foram notificados anteriormente" in up.message.sent[-1]


def test_admin_auctions_notify_samples_empty_with_fallback_suggests_preview_send(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    monkeypatch.setattr(
        handlers_admin,
        "build_auction_notification_samples",
        lambda _db, limit=10: {"created_at": "-", "summary": {}, "samples": [], "rejections": [{"reason": "item_type_not_allowed"}]},
    )
    db.add(AppKV(key="auction_last_previewable_auction_sample", value={"created_at": "2026-05-18T00:00:00+00:00", "source": "dry_run", "sample": {"title": "VW"}}))
    db.commit()
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "notify-samples")))
    assert "Há uma amostra anterior disponível para preview visual:" in up.message.sent[-1]
    assert "/admin auctions preview-send" in up.message.sent[-1]


def test_admin_auctions_notify_run_adds_operational_readings(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    monkeypatch.setattr(
        handlers_admin, "get_auction_notification_runtime_settings",
        lambda _db: {"dry_run": True, "max_wishlists_per_run": 5, "max_per_wishlist": 5, "max_per_user_per_day": 2}
    )
    async def _job(*_a, **_k):
        return {"sent": 0, "previews": 0, "skipped_duplicate": 2, "skipped_item_type_not_allowed": 1}
    monkeypatch.setattr(handlers_admin, "run_auction_notification_job", _job)
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "notify-run")))
    text = up.message.sent[-1]
    assert "Leitura: nenhum novo alerta enviado porque os matches elegíveis já foram notificados." in text
    assert "Leitura: lotes fora da categoria permitida foram bloqueados antes do score." in text


def test_admin_auctions_preview_send_uses_current_sample_first_then_fallback(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    monkeypatch.setattr(handlers_admin, "build_auction_notification_samples", lambda _db, limit=1: {"samples": []})
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "preview-send")))
    assert "Não há amostra disponível." in up.message.sent[-1]

    sample = {"wishlist_query": "touareg", "source": "vip_auctions", "title": "VW Touareg", "url": "https://vip/touareg", "score": 82}
    monkeypatch.setattr(handlers_admin, "build_auction_notification_samples", lambda _db, limit=1: {"samples": [sample]})
    sent = {}
    class _Bot:
        async def send_message(self, **kwargs):
            sent.update(kwargs)
    up2 = _Update(chat_id=4321)
    up2.get_bot = lambda: _Bot()
    before = db.query(AppKV).count()
    asyncio.run(handlers_admin.cmd_admin(up2, _ctx("auctions", "preview-send")))
    assert sent["chat_id"] == 4321
    assert "Preview admin — não enviado ao usuário" in sent["text"]
    assert sent["disable_web_page_preview"] is True
    markup = sent["reply_markup"].to_dict()
    assert markup["inline_keyboard"][0][0]["text"] == "🔗 Ver leilão"
    assert db.query(AppKV).count() == before

    sent2 = {}
    db.add(AppKV(key="auction_last_previewable_auction_sample", value={"created_at": "2026-05-18T00:00:00+00:00", "source": "dry_run", "sample": {"wishlist_query": "fallback", "source": "vip_auctions", "title": "Fallback", "url": "https://vip/fallback", "score": 79}}))
    db.commit()
    monkeypatch.setattr(handlers_admin, "build_auction_notification_samples", lambda _db, limit=1: {"samples": []})
    class _Bot2:
        async def send_message(self, **kwargs):
            sent2.update(kwargs)
    up3 = _Update(chat_id=1234)
    up3.get_bot = lambda: _Bot2()
    before2 = db.query(AppKV).count()
    asyncio.run(handlers_admin.cmd_admin(up3, _ctx("auctions", "preview-send")))
    assert "usando última amostra elegível conhecida" in sent2["text"]
    assert "usando última amostra elegível conhecida" in up3.message.sent[-2]
    assert sent2["reply_markup"].to_dict()["inline_keyboard"][0][0]["text"] == "🔗 Ver leilão"
    assert db.query(AppKV).count() == before2


def test_admin_auctions_preview_send_requires_admin(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: False)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    up = _Update(chat_id=11)
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "preview-send")))
    assert "Sem permissão" in up.message.sent[-1]

def test_admin_auctions_pilot_admin_only(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: False)
    up = _Update(chat_id=123)
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "pilot")))
    assert "Sem permissão" in up.message.sent[-1]


def test_admin_auctions_pilot_renders_and_read_only(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)

    called = {"run": 0, "user_send": 0}

    async def _forbidden_run(*_args, **_kwargs):
        called["run"] += 1
        return {}

    monkeypatch.setattr(handlers_admin, "run_auction_notification_job", _forbidden_run)
    monkeypatch.setattr(handlers_admin, "build_auction_pilot_status", lambda _db: {
        "mode": {"scheduler_enabled": True, "scheduler_dry_run": True, "manual_real_available": True, "automatic_real_active": False},
        "sources": {"user_eligible": ["vip_auctions"], "ready_car_pilot": ["vip_auctions"], "experimental_enabled": ["mega_auctions"], "unsafe_user_eligible": []},
        "wishlists": {"active_total": 12, "include_auctions_total": 2, "users_with_auction_wishlists": 1},
        "notifications": {"last_manual_real_at": "2026-05-19 10:23 UTC", "last_manual_real_sent": 0, "last_manual_real_duplicates": 1, "last_manual_real_errors": 0, "manual_real_sent_24h": 1, "duplicates_24h": 1, "last_dry_run_at": "2026-05-19 17:30 UTC", "last_dry_run_previews": 0, "dry_run_previews_24h": 0, "dry_run_history_partial": False, "top_rejections": ["item_type_not_allowed", "stale_lot"]},
        "health": {"status": "warning", "checks": [{"status": "ok", "label": "VIP é a única source user-facing", "detail": "ok"}]},
    })

    up = _Update(chat_id=123)
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "pilot")))
    text = up.message.sent[-1]
    assert "Admin Leilões — piloto" in text
    assert "Adoção:" in text
    assert "Sources user-facing:" in text
    assert "Envios reais manuais:" in text
    assert "Próximos comandos:" in text
    assert called["run"] == 0

    row = db.query(AppKV).filter(AppKV.key == "auction_notification_settings").first()
    assert not row or row.value.get("dry_run") is not False


def test_admin_quality_renders_user_facing_reason_for_win(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    db.add(SourceConfig(source="win_auctions", source_type="auction", is_enabled=True, user_eligible=False, status="experimental_vehicle_route_found", extra={"allowed_item_types":["car"]}))
    upsert_lot(db, {"source": "win_auctions", "external_id": "win-car-q", "title": "Civic", "item_type": "car", "year": 2020, "initial_bid": 10000, "url": "https://win/car-q", "status": "live", "auction_start_at": datetime.now(timezone.utc)})
    db.commit()
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "quality", "win")))
    text = up.message.sent[-1]
    assert "Qualidade dados car" in text
    assert "Pronta user-facing car: não" in text
    assert "Com início:" in text
    assert "Motivo user-facing:" in text
    assert "sem encerramento" in text


def test_admin_readiness_win_shows_experimental_not_user_facing(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    db.add(SourceConfig(source="win_auctions", source_type="auction", is_enabled=True, user_eligible=False, status="experimental_vehicle_route_found", extra={"allowed_item_types":["car"]}))
    upsert_lot(db, {"source": "win_auctions", "external_id": "wcar1", "item_type": "car", "year": 2020, "initial_bid": 1000, "url": "https://win/wcar1", "status": "live", "auction_start_at": datetime.now(timezone.utc)})
    lot = db.query(AuctionLot).filter_by(source="win_auctions", external_id="wcar1").first()
    if lot:
        lot.updated_at = datetime.now(timezone.utc)
    db.commit()
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "readiness")))
    text = up.message.sent[-1]
    assert "win_auctions:" in text
    assert "dados_car=sim" in text
    assert "status/live=sim" in text
    assert "início=sim" in text
    assert "encerramento=não" in text
    assert "user_facing=não" in text
