import uuid
from datetime import datetime, timezone

from app.models.app_kv import AppKV
from app.models.auction_lot import AuctionLot
from app.models.user import User
from app.models.wishlist import Wishlist
from app.services.auction_lot_service import upsert_lot
from app.services.auction_notification_service import build_auction_notifications_for_wishlist, send_auction_notifications_for_wishlist
from app.services.auction_notification_job_service import run_auction_notification_job
from app.models.source_config import SourceConfig
from app.core.settings import settings
from app.services.app_kv_service import set_kv
from app.bot.renderers import build_auction_alert_keyboard, render_auction_alert


import pytest


@pytest.fixture(autouse=True)
def _relax_notify_gates(monkeypatch):
    monkeypatch.setattr(settings, "auction_notifications_min_score", 0)
    monkeypatch.setattr(settings, "auction_notifications_max_lot_age_hours", 0)


def test_wishlist_not_found(db):
    res = build_auction_notifications_for_wishlist(db, str(uuid.uuid4()))
    assert res["errors"] == 1


def test_include_auctions_block_and_force(db):
    u = User(id=uuid.uuid4(), telegram_chat_id=111, username="u")
    db.add(u); db.flush()
    w = Wishlist(user_id=u.id, query="civic", is_active=True, include_auctions=False)
    db.add(w); db.flush()
    upsert_lot(db, {"source": "vip_auctions", "external_id": "x1", "title": "civic", "status": "open", "url": "https://lot/1"})
    db.commit()
    assert build_auction_notifications_for_wishlist(db, w.id)["errors"] == 1
    assert build_auction_notifications_for_wishlist(db, w.id, force=True)["errors"] == 0


def test_missing_chat_no_send(db):
    u = User(id=uuid.uuid4(), telegram_chat_id=0, username="u")
    db.add(u); db.flush()
    w = Wishlist(user_id=u.id, query="civic", is_active=True, include_auctions=True)
    db.add(w); db.commit()
    res = build_auction_notifications_for_wishlist(db, w.id)
    assert res["skipped_missing_chat_id"] == 1


def test_send_and_dedupe_and_filters(db):
    u = User(id=uuid.uuid4(), telegram_chat_id=222, username="u")
    db.add(u); db.flush()
    w = Wishlist(user_id=u.id, query="civic 2015", is_active=True, include_auctions=True)
    db.add(w); db.flush()
    upsert_lot(db, {"source": "vip_auctions", "external_id": "a1", "title": "Honda Civic 2015", "year": 2015, "status": "ended", "item_type": "car", "url": "https://lot/a1"})
    upsert_lot(db, {"source": "vip_auctions", "external_id": "a2", "title": "Honda Civic 2015", "year": 2015, "status": "open", "item_type": "car", "url": None})
    upsert_lot(db, {"source": "vip_auctions", "external_id": "a3", "title": "Honda Civic 2015", "year": 2015, "status": "open", "item_type": "car", "current_bid": 120000, "url": "https://lot/a3"})
    db.commit()

    sent_msgs = []
    class Bot:
        async def send_message(self, **kwargs):
            sent_msgs.append(kwargs)

    import asyncio
    res = asyncio.run(send_auction_notifications_for_wishlist(db, Bot(), w.id, limit=5))
    assert res["sent"] == 1
    assert sent_msgs and "Preview" not in sent_msgs[0]["text"]

    res2 = asyncio.run(send_auction_notifications_for_wishlist(db, Bot(), w.id, limit=1))
    assert res2["skipped_duplicate"] >= 1

    forced = build_auction_notifications_for_wishlist(db, w.id, force=True, limit=4)
    assert forced["sent"] <= 3
    assert any(isinstance(x, AppKV) for x in db.query(AppKV).all())


def test_build_dry_run_does_not_send_or_persist(db):
    u = User(id=uuid.uuid4(), telegram_chat_id=444, username="u")
    db.add(u); db.flush()
    w = Wishlist(user_id=u.id, query="civic 2015", is_active=True, include_auctions=True)
    db.add(w); db.flush()
    upsert_lot(
        db,
        {
            "source": "vip_auctions",
            "external_id": "dry1",
            "title": "Honda Civic 2015",
            "year": 2015,
            "mileage_km": 128468,
            "total_bids": 0,
            "auction_end_at": datetime(2026, 5, 20, 15, 0, tzinfo=timezone.utc),
            "location": "São Paulo/SP",
            "item_type": "car",
            "status": "open",
            "initial_bid": 80000,
            "url": "https://lot/dry1",
        },
    )
    db.commit()

    res = build_auction_notifications_for_wishlist(db, w.id, limit=1)
    assert res["sent"] == 1
    assert len(res.get("items", [])) == 1
    item = res["items"][0]
    assert item["source"] == "vip_auctions"
    assert item["external_id"] == "dry1"
    assert item["title"] == "Honda Civic 2015"
    assert item["current_bid"] is None
    assert item["initial_bid"] == 80000
    assert item["score"] is not None
    assert item["url"] == "https://lot/dry1"
    assert item["lot_id"]
    assert item["source_label"] == "VIP Leilões"
    assert item["year"] == 2015
    assert item["mileage_km"] == 128468
    assert item["total_bids"] == 0
    assert item["auction_end_at"].year == 2026
    assert item["auction_end_at"].month == 5
    assert item["auction_end_at"].day == 20
    assert item["location"] == "São Paulo/SP"
    assert item["item_type"] == "car"
    assert "Ano/KM: 2015/128.468" in item["text"]
    assert "Lances: 0" in item["text"]
    assert db.query(AppKV).count() == 0


def test_no_match(db):
    u = User(id=uuid.uuid4(), telegram_chat_id=333, username="u")
    db.add(u); db.flush()
    w = Wishlist(user_id=u.id, query="termo inexistente", is_active=True, include_auctions=True)
    db.add(w); db.commit()
    res = build_auction_notifications_for_wishlist(db, w.id)
    assert res["skipped_no_match"] >= 1


def test_notify_source_filter_with_eligible_sources(db):
    u = User(id=uuid.uuid4(), telegram_chat_id=555, username="u")
    db.add(u); db.flush()
    w = Wishlist(user_id=u.id, query="civic 2015", is_active=True, include_auctions=True)
    db.add(w); db.flush()
    upsert_lot(db, {"source": "mega_auctions", "external_id": "m1", "title": "Honda Civic 2015", "year": 2015, "status": "open", "url": "https://lot/m1"})
    db.commit()
    blocked = build_auction_notifications_for_wishlist(db, w.id, source="mega_auctions", eligible_sources={"vip_auctions"})
    assert blocked["sent"] == 0
    allowed = build_auction_notifications_for_wishlist(db, w.id, source="mega_auctions", eligible_sources=None)
    assert allowed["sent"] >= 0


def test_notify_prefers_bid_when_score_ties(db):
    u = User(id=uuid.uuid4(), telegram_chat_id=777, username="rank")
    db.add(u); db.flush()
    w = Wishlist(user_id=u.id, query="honda civic", is_active=True, include_auctions=True)
    db.add(w); db.flush()
    upsert_lot(db, {"source": "vip_auctions", "external_id": "t1", "title": "Honda Civic", "status": "open", "item_type": "car", "url": "https://lot/t1"})
    upsert_lot(db, {"source": "vip_auctions", "external_id": "t2", "title": "Honda Civic", "status": "open", "item_type": "car", "current_bid": 1000, "url": "https://lot/t2"})
    db.commit()
    res = build_auction_notifications_for_wishlist(db, w.id, limit=1)
    assert res["sent"] == 1
    assert "https://lot/t2" not in res["items"][0]["text"]
    assert res["items"][0]["reply_markup"] is not None


def test_render_auction_alert_has_no_link_or_url():
    m = type("M", (), {"source": "vip_auctions", "title": "Honda Civic", "wishlist_query": "civic", "current_bid": 1000, "url": "https://x"})()
    text = render_auction_alert(m)
    assert "Link:" not in text
    assert "https://x" not in text


def test_render_auction_alert_disclosure_is_visible_before_details():
    m = type("M", (), {"source": "vip_auctions", "title": "Honda Civic", "wishlist_query": "civic", "current_bid": 1000, "url": "https://x"})()
    text = render_auction_alert(m)

    assert "Lance não é preço final" in text
    assert text.index("Lance não é preço final") < text.index("Fonte:")


def test_build_auction_alert_keyboard():
    kb = build_auction_alert_keyboard("https://x")
    assert kb is not None
    assert kb.inline_keyboard[0][0].text == "🔗 Ver leilão"
    assert kb.inline_keyboard[0][0].url == "https://x"


def test_notify_blocks_no_bid_by_default_and_allow_no_bid(db):
    u = User(id=uuid.uuid4(), telegram_chat_id=778, username="nobid")
    db.add(u); db.flush()
    w = Wishlist(user_id=u.id, query="honda civic", is_active=True, include_auctions=True)
    db.add(w); db.flush()
    upsert_lot(db, {"source": "vip_auctions", "external_id": "nb1", "title": "Honda Civic", "status": "open", "item_type": "car", "url": "https://lot/nb1"})
    db.commit()
    blocked = build_auction_notifications_for_wishlist(db, w.id, limit=1)
    assert blocked["sent"] == 0
    assert "nenhum match com lance atual ou lance inicial" in blocked["messages"][0]
    allowed = build_auction_notifications_for_wishlist(db, w.id, limit=1, allow_no_bid=True)
    assert allowed["sent"] == 1


def test_notify_score_and_stale_gates(monkeypatch, db):
    monkeypatch.setattr(settings, "auction_notifications_min_score", 0)
    monkeypatch.setattr(settings, "auction_notifications_max_lot_age_hours", 48)
    u = User(id=uuid.uuid4(), telegram_chat_id=999, username="gates")
    db.add(u); db.flush()
    w = Wishlist(user_id=u.id, query="honda civic", is_active=True, include_auctions=True)
    db.add(w); db.flush()
    upsert_lot(db, {"source": "vip_auctions", "external_id": "g1", "title": "Honda Civic", "status": "open", "item_type": "car", "current_bid": 1000, "url": "https://lot/g1", "updated_at": datetime.now(timezone.utc)})
    upsert_lot(db, {"source": "vip_auctions", "external_id": "g2", "title": "Honda Civic", "status": "open", "item_type": "car", "current_bid": 1000, "url": "https://lot/g2", "updated_at": datetime(2020,1,1,tzinfo=timezone.utc)})
    db.commit()
    out = build_auction_notifications_for_wishlist(db, w.id, limit=5)
    assert out["skipped_score_below_min"] >= 0
    assert out["skipped_stale_lot"] >= 1


def test_notify_disable_age_filter_when_non_positive(monkeypatch, db):
    monkeypatch.setattr(settings, "auction_notifications_min_score", 0)
    monkeypatch.setattr(settings, "auction_notifications_max_lot_age_hours", 0)
    u = User(id=uuid.uuid4(), telegram_chat_id=1000, username="noage")
    db.add(u); db.flush()
    w = Wishlist(user_id=u.id, query="honda civic", is_active=True, include_auctions=True)
    db.add(w); db.flush()
    upsert_lot(db, {"source": "vip_auctions", "external_id": "old", "title": "Honda Civic", "status": "open", "item_type": "car", "initial_bid": 1000, "url": "https://lot/old", "updated_at": datetime(2020,1,1,tzinfo=timezone.utc)})
    db.commit()
    out = build_auction_notifications_for_wishlist(db, w.id, limit=1)
    assert out["sent"] == 1


def test_notify_quality_message_for_low_score_with_bid(monkeypatch, db):
    monkeypatch.setattr(settings, "auction_notifications_min_score", 101)
    monkeypatch.setattr(settings, "auction_notifications_max_lot_age_hours", 0)
    u = User(id=uuid.uuid4(), telegram_chat_id=1001, username="low-score")
    db.add(u); db.flush()
    w = Wishlist(user_id=u.id, query="honda civic", is_active=True, include_auctions=True)
    db.add(w); db.flush()
    upsert_lot(db, {"source": "vip_auctions", "external_id": "ls1", "title": "Honda Civic", "status": "open", "item_type": "car", "current_bid": 1000, "url": "https://lot/ls1"})
    db.commit()
    out = build_auction_notifications_for_wishlist(db, w.id, limit=1)
    assert out["sent"] == 0
    assert out["skipped_score_below_min"] >= 1
    assert "após filtros de qualidade" in out["messages"][0]


def test_notify_quality_message_for_stale_lot_with_bid(monkeypatch, db):
    monkeypatch.setattr(settings, "auction_notifications_min_score", 0)
    monkeypatch.setattr(settings, "auction_notifications_max_lot_age_hours", 1)
    u = User(id=uuid.uuid4(), telegram_chat_id=1002, username="stale")
    db.add(u); db.flush()
    w = Wishlist(user_id=u.id, query="honda civic", is_active=True, include_auctions=True)
    db.add(w); db.flush()
    upsert_lot(db, {"source": "vip_auctions", "external_id": "st1", "title": "Honda Civic", "status": "open", "item_type": "car", "current_bid": 1000, "url": "https://lot/st1", "updated_at": datetime(2020, 1, 1, tzinfo=timezone.utc)})
    db.commit()
    out = build_auction_notifications_for_wishlist(db, w.id, limit=1)
    assert out["sent"] == 0
    assert out["skipped_stale_lot"] >= 1
    assert "após filtros de qualidade" in out["messages"][0]


def test_runtime_min_score_overrides_env(db, monkeypatch):
    monkeypatch.setattr(settings, "auction_notifications_min_score", 60)
    u = User(id=uuid.uuid4(), telegram_chat_id=3001, username="runtime-score")
    db.add(u); db.flush()
    w = Wishlist(user_id=u.id, query="honda civic", is_active=True, include_auctions=True)
    db.add(w); db.flush()
    upsert_lot(db, {"source": "vip_auctions", "external_id": "rs1", "title": "Honda Civic", "status": "open", "item_type": "car", "current_bid": 1000, "url": "https://lot/rs1"})
    db.commit()
    set_kv(db, "auction_notification_settings", {"min_score": 90})
    out = build_auction_notifications_for_wishlist(db, w.id, limit=1)
    assert out["sent"] == 0
    assert out["skipped_score_below_min"] >= 1


def test_runtime_max_lot_age_zero_disables_age_filter(db):
    u = User(id=uuid.uuid4(), telegram_chat_id=3002, username="runtime-age")
    db.add(u); db.flush()
    w = Wishlist(user_id=u.id, query="honda civic", is_active=True, include_auctions=True)
    db.add(w); db.flush()
    upsert_lot(db, {"source": "vip_auctions", "external_id": "ra1", "title": "Honda Civic", "status": "open", "item_type": "car", "initial_bid": 1000, "url": "https://lot/ra1", "updated_at": datetime(2020,1,1,tzinfo=timezone.utc)})
    db.commit()
    set_kv(db, "auction_notification_settings", {"max_lot_age_hours": 0, "min_score": 0})
    out = build_auction_notifications_for_wishlist(db, w.id, limit=1)
    assert out["sent"] == 1


def test_runtime_fallback_to_env_when_no_appkv(db, monkeypatch):
    monkeypatch.setattr(settings, "auction_notifications_min_score", 99)
    u = User(id=uuid.uuid4(), telegram_chat_id=3003, username="runtime-fallback")
    db.add(u); db.flush()
    w = Wishlist(user_id=u.id, query="honda civic", is_active=True, include_auctions=True)
    db.add(w); db.flush()
    upsert_lot(db, {"source": "vip_auctions", "external_id": "rf1", "title": "Honda Civic", "status": "open", "item_type": "car", "current_bid": 1000, "url": "https://lot/rf1"})
    db.commit()
    out = build_auction_notifications_for_wishlist(db, w.id, limit=1)
    assert out["sent"] == 0


def test_category_gate_blocks_non_car_and_missing_type_by_default(db):
    u = User(id=uuid.uuid4(), telegram_chat_id=2001, username="cat")
    db.add(u); db.flush()
    w = Wishlist(user_id=u.id, query="honda civic", is_active=True, include_auctions=True)
    db.add(w); db.flush()
    upsert_lot(db, {"source": "vip_auctions", "external_id": "c1", "title": "Honda Civic", "item_type": "car", "status": "open", "current_bid": 10, "url": "https://lot/c1"})
    upsert_lot(db, {"source": "vip_auctions", "external_id": "m1", "title": "Honda Civic Moto", "item_type": "motorcycle", "status": "open", "current_bid": 10, "url": "https://lot/m1"})
    upsert_lot(db, {"source": "vip_auctions", "external_id": "t1", "title": "Honda Civic Truck", "item_type": "truck", "status": "open", "current_bid": 10, "url": "https://lot/t1"})
    upsert_lot(db, {"source": "vip_auctions", "external_id": "r1", "title": "Honda Civic Casa", "item_type": "real_estate", "status": "open", "current_bid": 10, "url": "https://lot/r1"})
    upsert_lot(db, {"source": "vip_auctions", "external_id": "o1", "title": "Honda Civic Outro", "item_type": "other", "status": "open", "current_bid": 10, "url": "https://lot/o1"})
    upsert_lot(db, {"source": "vip_auctions", "external_id": "n1", "title": "Honda Civic Sem Tipo", "item_type": None, "status": "open", "current_bid": 10, "url": "https://lot/n1"})
    db.commit()
    out = build_auction_notifications_for_wishlist(db, w.id, limit=5, allow_no_bid=True)
    assert out["sent"] == 1
    assert out["skipped_item_type_not_allowed"] >= 4
    assert out["skipped_missing_item_type"] >= 0


def test_category_gate_allows_motorcycle_when_configured(db):
    u = User(id=uuid.uuid4(), telegram_chat_id=2002, username="cat2")
    db.add(u); db.flush()
    w = Wishlist(user_id=u.id, query="moto honda", is_active=True, include_auctions=True)
    db.add(w); db.flush()
    cfg = db.query(SourceConfig).filter(SourceConfig.source == "vip_auctions").first() or SourceConfig(source="vip_auctions", source_type="auction", is_enabled=True, user_eligible=True)
    cfg.extra = {"allowed_item_types": ["car", "motorcycle"]}
    db.add(cfg)
    upsert_lot(db, {"source": "vip_auctions", "external_id": "mc2", "title": "Moto Honda", "item_type": "motorcycle", "status": "open", "current_bid": 10, "url": "https://lot/mc2"})
    db.commit()
    out = build_auction_notifications_for_wishlist(db, w.id, limit=1)
    assert out["sent"] == 1


def test_notify_job_summary_includes_category_skip_counters(db, monkeypatch):
    u = User(id=uuid.uuid4(), telegram_chat_id=2003, username="cat3")
    db.add(u); db.flush()
    db.add(Wishlist(user_id=u.id, query="honda", is_active=True, include_auctions=True))
    db.commit()

    monkeypatch.setattr("app.services.auction_notification_job_service.list_user_eligible_auction_sources", lambda _db: {"vip_auctions"})
    monkeypatch.setattr(
        "app.services.auction_notification_job_service.build_auction_notifications_for_wishlist",
        lambda *_a, **_k: {"items": [], "messages": [], "errors": 0, "skipped_no_match": 0, "skipped_duplicate": 0, "skipped_missing_chat_id": 0, "skipped_score_below_min": 0, "skipped_stale_lot": 0, "skipped_missing_lot_updated_at": 0, "skipped_item_type_not_allowed": 2, "skipped_missing_item_type": 1},
    )
    import asyncio
    out = asyncio.run(run_auction_notification_job(db, bot=None, dry_run=True))
    assert out["skipped_item_type_not_allowed"] == 2
    assert out["skipped_missing_item_type"] == 1


def test_rejection_reason_stale_lot(db, monkeypatch):
    monkeypatch.setattr(settings, "auction_notifications_min_score", 0)
    monkeypatch.setattr(settings, "auction_notifications_max_lot_age_hours", 1)
    u = User(id=uuid.uuid4(), telegram_chat_id=9001, username="r1")
    db.add(u); db.flush()
    w = Wishlist(user_id=u.id, query="honda civic", is_active=True, include_auctions=True)
    db.add(w); db.flush()
    upsert_lot(db, {"source": "vip_auctions", "external_id": "rr1", "title": "Honda Civic", "item_type": "car", "status": "open", "current_bid": 10, "url": "https://lot/rr1", "updated_at": datetime(2020, 1, 1, tzinfo=timezone.utc)})
    db.commit()
    out = build_auction_notifications_for_wishlist(db, w.id)
    assert any(r["reason"] == "stale_lot" for r in out["rejections"])


def test_rejection_reason_missing_updated_at(db, monkeypatch):
    monkeypatch.setattr(settings, "auction_notifications_min_score", 0)
    monkeypatch.setattr(settings, "auction_notifications_max_lot_age_hours", 1)
    u = User(id=uuid.uuid4(), telegram_chat_id=9002, username="r2")
    db.add(u); db.flush()
    w = Wishlist(user_id=u.id, query="honda civic", is_active=True, include_auctions=True)
    db.add(w); db.flush()
    upsert_lot(db, {"source": "vip_auctions", "external_id": "rr2", "title": "Honda Civic", "item_type": "car", "status": "open", "current_bid": 10, "url": "https://lot/rr2"})
    db.commit()
    monkeypatch.setattr(
        "app.services.auction_notification_service._is_auction_match_notification_eligible",
        lambda *_a, **_k: (False, "missing_lot_updated_at"),
    )
    out = build_auction_notifications_for_wishlist(db, w.id)
    assert any(r["reason"] == "missing_lot_updated_at" for r in out["rejections"])


def test_rejection_reason_score_below_min(db, monkeypatch):
    monkeypatch.setattr(settings, "auction_notifications_min_score", 101)
    monkeypatch.setattr(settings, "auction_notifications_max_lot_age_hours", 0)
    u = User(id=uuid.uuid4(), telegram_chat_id=9003, username="r3")
    db.add(u); db.flush()
    w = Wishlist(user_id=u.id, query="honda civic", is_active=True, include_auctions=True)
    db.add(w); db.flush()
    upsert_lot(db, {"source": "vip_auctions", "external_id": "rr3", "title": "Honda Civic", "item_type": "car", "status": "open", "current_bid": 10, "url": "https://lot/rr3"})
    db.commit()
    out = build_auction_notifications_for_wishlist(db, w.id)
    assert any(r["reason"] == "score_below_min" for r in out["rejections"])


def test_rejection_reason_item_type_not_allowed(db):
    u = User(id=uuid.uuid4(), telegram_chat_id=9004, username="r4")
    db.add(u); db.flush()
    w = Wishlist(user_id=u.id, query="moto", is_active=True, include_auctions=True)
    db.add(w); db.flush()
    upsert_lot(db, {"source": "vip_auctions", "external_id": "rr4", "title": "Moto Honda", "item_type": "motorcycle", "status": "open", "current_bid": 10, "url": "https://lot/rr4"})
    db.commit()
    out = build_auction_notifications_for_wishlist(db, w.id)
    assert any(r["reason"] == "item_type_not_allowed" for r in out["rejections"])


def test_rejections_limited_to_five(db, monkeypatch):
    monkeypatch.setattr(settings, "auction_notifications_min_score", 0)
    monkeypatch.setattr(settings, "auction_notifications_max_lot_age_hours", 1)
    u = User(id=uuid.uuid4(), telegram_chat_id=9005, username="r5")
    db.add(u); db.flush()
    w = Wishlist(user_id=u.id, query="honda", is_active=True, include_auctions=True)
    db.add(w); db.flush()
    for i in range(8):
        upsert_lot(db, {"source": "vip_auctions", "external_id": f"rr5-{i}", "title": "Honda Civic", "item_type": "car", "status": "open", "current_bid": 10, "url": f"https://lot/rr5-{i}", "updated_at": datetime(2020, 1, 1, tzinfo=timezone.utc)})
    db.commit()
    out = build_auction_notifications_for_wishlist(db, w.id, limit=3)
    assert len(out["rejections"]) == 5


def test_rejection_current_bid_is_string(monkeypatch, db):
    monkeypatch.setattr(settings, "auction_notifications_min_score", 999)
    monkeypatch.setattr(settings, "auction_notifications_max_lot_age_hours", 0)
    u = User(id=uuid.uuid4(), telegram_chat_id=4001, username="rej")
    db.add(u); db.flush()
    w = Wishlist(user_id=u.id, query="honda civic", is_active=True, include_auctions=True)
    db.add(w); db.flush()
    upsert_lot(db, {"source": "vip_auctions", "external_id": "rej1", "title": "Honda Civic", "status": "open", "item_type": "car", "current_bid": 8500, "url": "https://lot/rej1"})
    db.commit()
    out = build_auction_notifications_for_wishlist(db, w.id, limit=1)
    assert out["rejections"]
    assert out["rejections"][0]["current_bid"] == "8500.00"
