"""End-to-end do caminho oficial: wishlist -> run da source -> scrape+ingestao -> dedupe ->
matching -> fila de notificacoes -> sender.

So fronteiras externas sao falsas: a pagina da source (plugin.scrape) e o Telegram (sender_fn).
Todo o resto roda de verdade contra o banco de teste: source_execution_service, ingestao,
matching, notifications_queue_service, delivery e limites do plano.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.models.car_listing import CarListing
from app.models.notification import Notification
from app.models.source_config import SourceConfig
from app.models.source_run import SourceRun
from app.models.user import User
from app.models.wishlist import Wishlist
from app.models.wishlist_filter import WishlistFilter
from app.models.wishlist_token import WishlistToken
from app.scheduler.jobs_send import send_queued_notifications
from app.services.wishlist_tokens_service import rebuild_tokens_for_wishlist
from app.services.source_execution_service import run_source_for_all_wishlists
from app.sources import registry
from app.sources.types import SourcePlugin

pytestmark = pytest.mark.e2e

SOURCE = "e2e_source"


def _listing(ext: str, title: str, price: float, year: int = 2020) -> dict:
    return {
        "source": SOURCE,
        "external_id": ext,
        "title": title,
        "url": f"https://example.test/{ext}",
        "price": price,
        "currency": "BRL",
        "year": year,
        "location": "Sao Paulo - SP",
    }


@pytest.fixture
def world(db, monkeypatch):
    """Usuario free com a busca 'civic exl' e uma source falsa configurada no banco."""
    user = User(id=uuid.uuid4(), telegram_chat_id=777, username="e2e", is_active=True, plan="free")
    wish = Wishlist(id=uuid.uuid4(), user_id=user.id, query="civic exl", is_active=True)
    db.add_all(
        [
            user,
            wish,
            # filtro explicito de source: a fonte falsa nao esta no registro de fontes padrao
            WishlistFilter(id=uuid.uuid4(), wishlist_id=wish.id, field="source", operator="eq", value=SOURCE, is_active=True),
            SourceConfig(
                source=SOURCE,
                is_enabled=True,
                sched_minutes=10,
                cooldown_minutes=0,
                rate_limit_seconds=0,
                browser_fallback_enabled=False,
                force_browser=False,
            ),
        ]
    )
    rebuild_tokens_for_wishlist(db, wish)  # indice de tokens usado pelo matching do scheduler
    db.commit()

    pages: list[list[dict]] = []
    behavior = {"scrape": None}

    def scrape(url, ctx=None, **_kw):
        if behavior["scrape"]:
            return behavior["scrape"]()
        return list(pages.pop(0)) if pages else []

    # Plugin REAL registrado no registro REAL (restaurado no fim do teste): assim elegibilidade,
    # roteamento e matching usam o mesmo caminho de producao.
    plugin = SourcePlugin(
        name=SOURCE,
        build_url=lambda q: f"https://example.test/search?q={q or ''}",
        scrape=scrape,
        supports_wishlist_monitoring=True,
        fetch_mode="http",
    )
    monkeypatch.setitem(registry._REGISTRY, SOURCE, plugin)
    monkeypatch.setattr("app.services.source_execution_service.get_scraper", lambda _s: None)

    # Cada grupo roda em sessao propria (como em producao, onde o Postgres nao bloqueia leitores/
    # escritores concorrentes). SQLite so tem um escritor: confirma a sessao do teste antes de
    # cada grupo para emular esse isolamento, sem alterar o codigo de producao.
    import app.services.source_execution_service as ses

    real_group = ses._process_group_isolated

    def _group_after_commit(*a, **k):
        db.commit()
        return real_group(*a, **k)

    monkeypatch.setattr(ses, "_process_group_isolated", _group_after_commit)
    return SimpleNamespace(user=user, wish=wish, pages=pages, behavior=behavior)


def _run(db):
    return run_source_for_all_wishlists(db, SOURCE, kind="scheduler", force=True, ignore_backoff=True, run_reason="scheduler")


def _send(db):
    sent: list[tuple[int, str]] = []

    def sender_fn(notification, listing, user):  # contrato real: send_queued_notifications -> sender_fn(n, listing, user)
        sent.append((user.telegram_chat_id, f"{listing.title} {listing.url}"))

    send_queued_notifications(db, "e2e_sender", sender_fn)
    db.commit()
    return sent


def test_new_matching_listing_is_ingested_matched_queued_and_sent(db, world):
    world.pages.append([_listing("a1", "Honda Civic EXL 2020", 95000), _listing("b2", "Fiat Uno 2012", 20000)])

    res = _run(db)

    assert res["ok"] is True
    assert {l.external_id for l in db.query(CarListing).filter_by(source=SOURCE)} == {"a1", "b2"}  # ingestao
    run = db.query(SourceRun).filter_by(source=SOURCE, status="success").one()
    assert run.items_found == 2
    queued = db.query(Notification).all()
    assert len(queued) == 1  # so o Civic casa com a busca; o Uno e ignorado
    assert queued[0].user_id == world.user.id and queued[0].wishlist_id == world.wish.id

    sent = _send(db)

    assert len(sent) == 1 and sent[0][0] == 777
    assert "Civic" in sent[0][1] and "example.test/a1" in sent[0][1]
    assert db.query(Notification).one().status == "sent"


def test_rerun_with_same_listing_does_not_duplicate_or_renotify(db, world):
    world.pages.extend([[_listing("a1", "Honda Civic EXL 2020", 95000)]] * 2)

    _run(db)
    _send(db)
    _run(db)
    sent_again = _send(db)

    assert db.query(CarListing).filter_by(source=SOURCE).count() == 1  # dedupe
    assert db.query(Notification).count() == 1
    assert sent_again == []


def test_free_plan_daily_limit_suppresses_extra_alerts(db, world, monkeypatch):
    monkeypatch.setattr("app.scheduler.jobs_send.get_active_subscription_limit_for_user", lambda _db, _uid: 1)
    monkeypatch.setattr("app.scheduler.jobs_send.send_daily_limit_notice_http", lambda *a, **k: True)
    world.pages.append([_listing("a1", "Honda Civic EXL 2020", 95000), _listing("a2", "Honda Civic EXL Touring 2019", 105000)])

    _run(db)
    sent = _send(db)

    statuses = sorted(n.status for n in db.query(Notification).all())
    assert len(sent) == 1  # o limite do plano e respeitado
    assert statuses.count("sent") == 1 and "suppressed" in statuses


def test_source_failure_is_recorded_and_notifies_nobody(db, world):
    def boom():
        raise RuntimeError("site fora do ar")

    world.behavior["scrape"] = boom

    _run(db)

    assert db.query(Notification).count() == 0
    assert db.query(CarListing).filter_by(source=SOURCE).count() == 0
    assert _send(db) == []


@pytest.mark.xfail(
    strict=True,
    reason=(
        "BUG conhecido: candidate_wishlist_ids_for_listing_tokens exige min_overlap=2 tokens, entao uma "
        "busca de UMA palavra (ex.: 'defender', 'cuore', 'rs4') nunca vira candidata no matching do "
        "scheduler e so recebe alertas no backfill da criacao. Remova o xfail ao corrigir."
    ),
)
def test_single_word_wishlist_is_matched_by_the_scheduler(db, world):
    world.wish.query = "civic"
    db.query(WishlistToken).filter_by(wishlist_id=world.wish.id).delete()
    rebuild_tokens_for_wishlist(db, world.wish)
    db.commit()
    world.pages.append([_listing("a1", "Honda Civic EXL 2020", 95000)])

    _run(db)

    assert db.query(Notification).count() == 1
