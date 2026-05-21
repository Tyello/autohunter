from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.models.user import User
from app.models.wishlist import Wishlist
from app.models.wishlist_filter import WishlistFilter
from app.services.source_execution_service import _wishlist_eligibility_snapshot
from app.services.wishlist_sources_service import get_eligible_wishlists_for_source


def _mk_user(db, *, chat_id: int = 900) -> User:
    u = User(id=uuid.uuid4(), telegram_chat_id=chat_id, username=f"u{chat_id}", is_active=True, plan="free")
    db.add(u)
    db.commit()
    return u


def _mk_wishlist(db, user_id, *, query: str, is_active: bool = True, source_filter: str | None = None) -> Wishlist:
    wl = Wishlist(id=uuid.uuid4(), user_id=user_id, query=query, is_active=is_active)
    db.add(wl)
    db.commit()
    if source_filter:
        db.add(WishlistFilter(wishlist_id=wl.id, field="source", operator="eq", value=source_filter))
        db.commit()
    return wl


def _patch_sources(monkeypatch):
    sources = [
        SimpleNamespace(name="olx", supports_wishlist_monitoring=True, scrape=object()),
        SimpleNamespace(name="mercadolivre", supports_wishlist_monitoring=True, scrape=object()),
        SimpleNamespace(name="placeholder", supports_wishlist_monitoring=True, scrape=None),
    ]
    monkeypatch.setattr("app.services.wishlist_sources_service.list_sources", lambda: sources)


def test_get_eligible_wishlists_for_source_rules_and_stats(db, monkeypatch):
    _patch_sources(monkeypatch)
    user = _mk_user(db)

    wl_active_no_filter = _mk_wishlist(db, user.id, query="civic")
    wl_active_olx = _mk_wishlist(db, user.id, query="gol", source_filter="olx")
    wl_active_ml = _mk_wishlist(db, user.id, query="uno", source_filter="mercadolivre")
    _mk_wishlist(db, user.id, query="inativo", is_active=False)
    wl_active_custom = _mk_wishlist(db, user.id, query="custom", source_filter="customsource")

    olx_wls, olx_stats = get_eligible_wishlists_for_source(db, "  OLX ")
    assert {w.id for w in olx_wls} == {wl_active_no_filter.id, wl_active_olx.id}
    assert olx_stats == {
        "total_wishlists": 5,
        "active_wishlists": 4,
        "eligible_wishlists": 2,
        "filtered_by_disabled": 1,
        "filtered_by_source_binding": 2,
        "filtered_by_plan": 0,
        "filtered_by_user_state": 0,
    }

    ml_wls, _ = get_eligible_wishlists_for_source(db, "mercadolivre")
    assert {w.id for w in ml_wls} == {wl_active_no_filter.id, wl_active_ml.id}

    custom_wls, custom_stats = get_eligible_wishlists_for_source(db, "customsource")
    assert {w.id for w in custom_wls} == {wl_active_custom.id}
    assert custom_stats["eligible_wishlists"] == 1


def test_get_eligible_equivalent_to_previous_rule(db, monkeypatch):
    _patch_sources(monkeypatch)
    user = _mk_user(db, chat_id=901)
    dataset = [
        _mk_wishlist(db, user.id, query="sem_filtro"),
        _mk_wishlist(db, user.id, query="olx", source_filter="olx"),
        _mk_wishlist(db, user.id, query="ml", source_filter="mercadolivre"),
        _mk_wishlist(db, user.id, query="off", is_active=False),
        _mk_wishlist(db, user.id, query="nao_default", source_filter="nao_default"),
    ]
    defaults = {"olx", "mercadolivre"}

    def old_rule(src: str):
        out = []
        for wl in dataset:
            if wl.is_active is False:
                continue
            src_filters = {
                f.value for f in wl.filters
                if (f.field or "") == "source" and (f.operator or "") == "eq" and f.value
            }
            allowed = src_filters if src_filters else defaults
            if src in allowed:
                out.append(wl.id)
        return set(out)

    for src in ("olx", "mercadolivre", "nao_default"):
        eligible, _ = get_eligible_wishlists_for_source(db, src)
        assert {w.id for w in eligible} == old_rule(src)


def test_source_execution_snapshot_delegates_to_helper(db, monkeypatch):
    _patch_sources(monkeypatch)
    user = _mk_user(db, chat_id=902)
    _mk_wishlist(db, user.id, query="sem_filtro")
    _mk_wishlist(db, user.id, query="olx", source_filter="olx")
    _mk_wishlist(db, user.id, query="ml", source_filter="mercadolivre")

    from_helper = get_eligible_wishlists_for_source(db, "olx")
    from_execution = _wishlist_eligibility_snapshot(db, "olx")

    assert [w.id for w in from_execution[0]] == [w.id for w in from_helper[0]]
    assert from_execution[1] == from_helper[1]
