import asyncio
import types
import uuid
from datetime import datetime, timezone

from app.bot import handlers_admin
from app.models.app_kv import AppKV
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


def test_admin_auctions_run_variants(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    monkeypatch.setattr(handlers_admin, "run_auction_ingestion", lambda **kwargs: {"source": "vip_auctions", "fetched": 10, "inserted": 2, "updated": 8, "skipped": 4, "errors": 0, "reason": None, "skipped_reasons": {"invalid_url": 2, "institutional_url": 2}})
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "run", "vip")))
    assert "Rodando leilões vip_auctions" in up.message.sent[-2]
    assert "limit: 10" in up.message.sent[-1]
    assert "duração_ms:" in up.message.sent[-1]
    assert "Ignorados:" in up.message.sent[-1]
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

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "source", "win")))
    assert "source win_auctions" in up.message.sent[-1] or "Nenhum lote persistido para source=win_auctions" in up.message.sent[-1]

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "source", "sodre")))
    assert "source sodre_auctions" in up.message.sent[-1] or "Nenhum lote persistido para source=sodre_auctions" in up.message.sent[-1]

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "source", "superbid")))
    assert "source superbid_auctions" in up.message.sent[-1] or "Nenhum lote persistido para source=superbid_auctions" in up.message.sent[-1]

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "match", "sodre")))
    assert "matching (somente leitura)" in up.message.sent[-1] or "Sem leilões compatíveis" in up.message.sent[-1]

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "match", "superbid")))
    assert "matching (somente leitura)" in up.message.sent[-1] or "Sem leilões compatíveis" in up.message.sent[-1]

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "match", "wishlist", str(w.id))))
    assert "🎯 Busca: civic 2015" in up.message.sent[-1]
    assert "Lance atual: R$ 91.000,00" in up.message.sent[-1]
    assert "Lance atual: R$ 91000.00" not in up.message.sent[-1]
    assert "Lance atual: -" in up.message.sent[-1]




def test_admin_auctions_source_invalid_shows_registry_hint(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
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


def test_admin_auctions_help_uses_registry_sources_hint(monkeypatch, db):
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    up = _Update()
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "acao_invalida")))
    assert "vip|mega|win|sodre|superbid|copart" in up.message.sent[-1]
    assert "/admin auctions match [vip|mega|win|sodre|superbid|copart|wishlist <id> [--force] [--all-sources]]" in up.message.sent[-1]


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
    assert "Lance atual:" in text
    assert "Lance inicial:" in text
    assert "preço final" not in text.lower()
    assert "Lance não é valor final" in text
    assert "https://example/lote" in text


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
    assert "Lance não é valor final" in text
    assert "preço final" not in text.lower()
    assert "Lance atual" in text and "Lance inicial" in text
    assert "https://example/lote" in text


def test_admin_auctions_notify_variants(monkeypatch, db):
    from app.models.user import User
    from app.models.wishlist import Wishlist
    u = User(id=uuid.uuid4(), telegram_chat_id=909, username="n")
    db.add(u); db.flush()
    w = Wishlist(user_id=u.id, query="civic 2015", is_active=True, include_auctions=True)
    db.add(w); db.flush()
    upsert_lot(db, {"source": "vip_auctions", "external_id": "n1", "title": "Honda Civic 2015", "year": 2015, "status": "open", "url": "https://vip/n1"})
    db.commit()

    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    up = _Update()
    up.get_bot = lambda: types.SimpleNamespace(send_message=(lambda **kwargs: asyncio.sleep(0)))

    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "notify", "wishlist", str(w.id))))
    assert "Dry-run: nenhum alerta foi enviado." in up.message.sent[-3]
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
    monkeypatch.setattr(handlers_admin, "is_admin", lambda _cid: True)
    monkeypatch.setattr(handlers_admin, "SessionLocal", lambda: _SessionWrap(db))
    up = _Update()
    up.get_bot = lambda: types.SimpleNamespace(send_message=(lambda **kwargs: asyncio.sleep(0)))

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
    asyncio.run(handlers_admin.cmd_admin(up, _ctx("auctions", "notify", "wishlist", str(uuid.uuid4()), "--confirm")))
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
