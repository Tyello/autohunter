from decimal import Decimal
import uuid

from app.models.user import User
from app.models.wishlist import Wishlist
from app.models.notification import Notification
from app.services.auction_lot_service import upsert_lot
from app.services.auction_matching_service import (
    debug_auction_lot_candidates_for_wishlist,
    match_auction_lots_for_all_wishlists,
    match_auction_lots_for_wishlist,
)


def _mk_wishlist(db, query: str):
    u = User(id=uuid.uuid4(), telegram_chat_id=70000 + (uuid.uuid4().int % 100000), username="admin")
    db.add(u)
    db.flush()
    w = Wishlist(user_id=u.id, query=query, is_active=True, include_auctions=True)
    db.add(w)
    db.commit()
    db.refresh(w)
    return w


def test_match_by_title_and_year_and_source_filter(db):
    w = _mk_wishlist(db, "civic si 2015")
    upsert_lot(db, {"source": "vip_auctions", "external_id": "a1", "title": "Honda Civic Si 2015", "year": 2015, "current_bid": Decimal("35000") ,"status": "open"})
    upsert_lot(db, {"source": "copart_auctions", "external_id": "a2", "title": "Honda Civic LX 2014", "year": 2014, "status": "open"})
    db.commit()

    matches = match_auction_lots_for_wishlist(db, w, limit=10)
    assert matches
    assert matches[0].source == "vip_auctions"
    assert matches[0].year == 2015
    assert matches[0].risk_label == "auction"

    vip_only = match_auction_lots_for_wishlist(db, w, source="vip_auctions", limit=10)
    assert vip_only
    assert all(m.source == "vip_auctions" for m in vip_only)


def test_filter_by_wishlist_and_no_notifications_created(db):
    w1 = _mk_wishlist(db, "corolla 2020")
    u2 = User(id=uuid.uuid4(), telegram_chat_id=70002, username="admin2")
    db.add(u2)
    db.flush()
    w2 = Wishlist(user_id=u2.id, query="civic 2015", is_active=True, include_auctions=False)
    db.add(w2)
    db.commit()
    db.refresh(w2)
    upsert_lot(db, {"source": "vip_auctions", "external_id": "x1", "title": "Toyota Corolla 2020", "year": 2020, "status": "open"})
    upsert_lot(db, {"source": "vip_auctions", "external_id": "x2", "title": "Honda Civic 2015", "year": 2015, "status": "open"})
    db.commit()

    all_matches = match_auction_lots_for_all_wishlists(db, source="vip_auctions", limit_per_wishlist=5)
    assert str(w1.id) in all_matches
    assert str(w2.id) not in all_matches

    only_w1 = match_auction_lots_for_wishlist(db, w1, source="vip_auctions", limit=5)
    assert only_w1
    assert any("corolla" in (m.title or "").lower() for m in only_w1)

    assert db.query(Notification).count() == 0


def test_no_matches_returns_empty(db):
    w = _mk_wishlist(db, "porsche 911")
    upsert_lot(db, {"source": "vip_auctions", "external_id": "z1", "title": "Uno Mille", "year": 2010, "status": "open"})
    db.commit()
    matches = match_auction_lots_for_wishlist(db, w, limit=5)
    assert matches == []


def test_match_for_all_wishlists_can_ignore_include_auctions_filter(db):
    w = _mk_wishlist(db, "uno")
    w.include_auctions = False
    db.add(w)
    upsert_lot(db, {"source": "vip_auctions", "external_id": "fa1", "title": "Fiat Uno", "status": "open"})
    db.commit()

    default_matches = match_auction_lots_for_all_wishlists(db, source="vip_auctions", limit_per_wishlist=5)
    assert str(w.id) not in default_matches

    forced_matches = match_auction_lots_for_all_wishlists(db, source="vip_auctions", limit_per_wishlist=5, include_auctions_only=False)
    assert str(w.id) in forced_matches


def test_debug_candidates_reports_filters_not_matched(db):
    w = _mk_wishlist(db, "civic")
    from app.services.wishlists_service import add_filter
    add_filter(db, w.id, "state", "eq", "SP")
    upsert_lot(db, {"source": "vip_auctions", "external_id": "d1", "title": "Honda Civic", "status": "open", "state": "RJ"})
    db.commit()
    out = debug_auction_lot_candidates_for_wishlist(db, w, limit=10)
    assert out
    assert any(x["reject_reason"] == "filters_not_matched" for x in out)


def test_debug_candidates_reports_text_score_zero(db):
    w = _mk_wishlist(db, "porsche")
    upsert_lot(db, {"source": "vip_auctions", "external_id": "d2", "title": "Fiat Uno", "status": "open"})
    db.commit()
    out = debug_auction_lot_candidates_for_wishlist(db, w, limit=10)
    assert any(x["reject_reason"] == "text_score_zero" for x in out)


def test_debug_candidates_reports_ok(db):
    w = _mk_wishlist(db, "honda civic")
    upsert_lot(db, {"source": "vip_auctions", "external_id": "d3", "title": "Honda Civic", "status": "open"})
    db.commit()
    out = debug_auction_lot_candidates_for_wishlist(db, w, limit=10)
    assert any(x["reject_reason"] == "ok" for x in out)


def test_single_model_term_gets_strong_score(db):
    scenarios = [
        ("touareg", "TOUAREG V8"),
        ("kicks", "KICKS S CVT"),
        ("ranger", "RANGER XL CD4 22C"),
        ("civic", "Honda Civic EXL"),
    ]
    for idx, (query, title) in enumerate(scenarios, start=1):
        w = _mk_wishlist(db, query)
        upsert_lot(
            db,
            {"source": "vip_auctions", "external_id": f"strong-{idx}", "title": title, "status": "open", "current_bid": Decimal("10000")},
        )
        db.commit()
        out = match_auction_lots_for_wishlist(db, w, source="vip_auctions", limit=5)
        assert out, (query, title)
        assert out[0].score >= 60, (query, title, out[0].score)


def test_generic_single_terms_do_not_force_strong_match(db):
    generic_cases = [("carro", "Honda Civic"), ("1.0", "HB20 1.0M")]
    for idx, (query, title) in enumerate(generic_cases, start=1):
        w = _mk_wishlist(db, query)
        upsert_lot(db, {"source": "vip_auctions", "external_id": f"generic-{idx}", "title": title, "status": "open", "current_bid": Decimal("10000")})
        db.commit()
        out = debug_auction_lot_candidates_for_wishlist(db, w, source="vip_auctions", limit=10)
        assert out
        row = next(x for x in out if x["external_id"] == f"generic-{idx}")
        assert "match forte de modelo/termo único" not in (row.get("reasons") or [])


def test_debug_candidates_respects_eligible_sources(db):
    w = _mk_wishlist(db, "honda")
    upsert_lot(db, {"source": "vip_auctions", "external_id": "d4", "title": "Honda City", "status": "open"})
    upsert_lot(db, {"source": "copart_auctions", "external_id": "d5", "title": "Honda Fit", "status": "open"})
    db.commit()
    out = debug_auction_lot_candidates_for_wishlist(db, w, eligible_sources={"vip_auctions"}, limit=10)
    assert out
    assert all(x["source"] == "vip_auctions" for x in out)
