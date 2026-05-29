from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy.exc import IntegrityError
from typing import Any

from sqlalchemy.orm import Session

from app.models.car_listing import CarListing
from app.models.notification import Notification
from app.models.wishlist import Wishlist
from app.models.wishlist_tracked_listing import WishlistTrackedListing
from app.core.settings import settings
from app.services.notifications_queue_service import queue_tracked_price_drop_alert
from app.services.price_tracking_service import sync_tracked_listing_price
from app.services.wishlists_service import invalidate_wishlist_summaries_cache
from app.services.wishlists_service import get_user_plan_snapshot
from app.services.plan_capabilities import (
    get_plan_capabilities,
    tracking_limit_message,
    tracking_slots_full_message,
)

MAX_TRACKED_PER_WISHLIST = 3

@dataclass
class TrackedListingResult:
    ok: bool
    status: str
    message: str
    wishlist_id: str | None = None
    wishlist_index: int | None = None
    tracked_listing_id: str | None = None
    car_listing_id: str | None = None
    slot: int | None = None
    already_tracked: bool = False
    automation_enabled: bool | None = None
    price: Decimal | None = None


@dataclass
class TrackingCapacitySnapshot:
    wishlist_id: str
    used_slots: list[int]
    free_slots: list[int]
    used_count: int
    max_slots: int
    can_add: bool


def _build_tracked_result(
    *,
    ok: bool,
    status: str,
    message: str,
    wishlist: Wishlist | None = None,
    wishlist_index: int | None = None,
    tracked: WishlistTrackedListing | None = None,
    listing: CarListing | None = None,
    slot: int | None = None,
    already_tracked: bool = False,
    automation_enabled: bool | None = None,
) -> TrackedListingResult:
    return TrackedListingResult(
        ok=ok,
        status=status,
        message=message,
        wishlist_id=str(wishlist.id) if wishlist and getattr(wishlist, "id", None) else None,
        wishlist_index=wishlist_index,
        tracked_listing_id=str(tracked.id) if tracked and getattr(tracked, "id", None) else None,
        car_listing_id=str(listing.id) if listing and getattr(listing, "id", None) else None,
        slot=(slot if slot is not None else (int(tracked.slot) if tracked and getattr(tracked, "slot", None) else None)),
        already_tracked=already_tracked,
        automation_enabled=automation_enabled,
        price=(listing.price if listing else None),
    )


def user_has_tracking_automation(db: Session, *, user_id) -> bool:
    try:
        snap = get_user_plan_snapshot(db, user_id)
    except Exception:
        return False
    plan_code = str((snap or {}).get("plan_code") or "free").strip().lower()
    return get_plan_capabilities(plan_code).tracking_auto_alerts


def _short_label(text: Any, *, max_len: int = 70) -> str:
    raw = str(text or "").strip()
    if not raw:
        return "Anúncio"
    compact = " ".join(raw.split())
    if len(compact) <= max_len:
        return compact
    return compact[: max(1, max_len - 1)].rstrip() + "…"


def _normalize_listing_ref(ref: str) -> str:
    raw = (ref or "").strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    if not parts.scheme or not parts.netloc:
        return raw
    clean = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))
    return clean


def _fmt_price(price: Decimal | None) -> str:
    if price is None:
        return "sem informação"
    return f"R$ {int(price):,}".replace(",", ".")


def _fmt_dt(dt: datetime | None) -> str:
    if not dt:
        return "sem informação"
    return dt.astimezone(timezone.utc).strftime("%d/%m/%Y %H:%M")


def refresh_tracked_listing_snapshot(
    db: Session, tracked: WishlistTrackedListing, listing: CarListing | None = None
) -> dict[str, Any]:
    listing_row = listing
    if listing_row is None and tracked.car_listing_id:
        listing_row = db.query(CarListing).filter(CarListing.id == tracked.car_listing_id).first()

    result = sync_tracked_listing_price(db, tracked, listing_row)
    return {"status": result.status, "direction": result.direction, "should_alert_price_drop": result.should_alert_price_drop}


def evaluate_price_drop_alert(db: Session, tracked: WishlistTrackedListing, change_summary: dict[str, Any]) -> bool:
    if not tracked.price_drop_alert_enabled:
        return False
    if not tracked.wishlist_id or not tracked.car_listing_id:
        return False
    if (change_summary or {}).get("direction") != "dropped":
        return False
    current_price = tracked.last_observed_price
    amount = tracked.last_price_change_amount
    pct = tracked.last_price_change_pct
    if current_price is None or amount is None:
        return False
    if amount >= 0:
        return False
    if tracked.last_price_drop_alert_price is not None and current_price >= tracked.last_price_drop_alert_price:
        return False
    min_abs = Decimal(str(getattr(settings, "tracking_price_drop_alert_min_amount", 500) or 500))
    min_pct = Decimal(str(getattr(settings, "tracking_price_drop_alert_min_pct", 1.0) or 1.0)) / Decimal("100")
    if abs(amount) < min_abs and (pct is None or abs(pct) < min_pct):
        return False

    cooldown_h = int(getattr(settings, "tracking_price_drop_alert_cooldown_hours", 24) or 24)
    if tracked.last_price_drop_alert_at is not None:
        delta = datetime.now(timezone.utc) - tracked.last_price_drop_alert_at
        if delta.total_seconds() < cooldown_h * 3600:
            return False

    queued = queue_tracked_price_drop_alert(db, tracked=tracked)
    if not queued:
        return False
    tracked.last_price_drop_alert_at = datetime.now(timezone.utc)
    tracked.last_price_drop_alert_price = current_price
    return True


def _wishlist_from_index(db: Session, *, user_id, wishlist_index: int) -> Wishlist | None:
    rows = (
        db.query(Wishlist)
        .filter(Wishlist.user_id == user_id)
        .order_by(Wishlist.created_at.asc())
        .all()
    )
    if wishlist_index < 1 or wishlist_index > len(rows):
        return None
    return rows[wishlist_index - 1]


def _find_listing(db: Session, listing_ref: str) -> CarListing | None:
    ref = _normalize_listing_ref(listing_ref)
    if not ref:
        return None

    row = db.query(CarListing).filter(CarListing.external_id == ref).order_by(CarListing.created_at.desc()).first()
    if row:
        return row

    row = db.query(CarListing).filter(CarListing.url == ref).order_by(CarListing.created_at.desc()).first()
    if row:
        return row

    # Fallback: match by canonical url (without query/fragment).
    for cand in db.query(CarListing).order_by(CarListing.created_at.desc()).limit(300).all():
        if _normalize_listing_ref(getattr(cand, "url", "") or "") == ref:
            return cand
    return None


def add_tracked_listing_result(
    db: Session, *, user_id, wishlist_index: int, listing_ref: str
) -> TrackedListingResult:
    wishlist = _wishlist_from_index(db, user_id=user_id, wishlist_index=wishlist_index)
    if not wishlist:
        return _build_tracked_result(
            ok=False,
            status="wishlist_not_found",
            message="Wishlist não encontrada para você. Use /wishlist para listar os índices válidos.",
            wishlist_index=wishlist_index,
        )

    listing = _find_listing(db, listing_ref)
    if not listing:
        return _build_tracked_result(
            ok=False,
            status="listing_not_found",
            message="Não encontrei esse anúncio no AutoHunter. Tente external_id exato ou URL já ingerida.",
            wishlist=wishlist,
            wishlist_index=wishlist_index,
        )

    listing_status = "inactive" if getattr(listing, "is_sold", False) else "active"
    if listing_status != "active":
        return _build_tracked_result(
            ok=False,
            status="unavailable",
            message="Não consegui rastrear esse anúncio porque ele não está mais disponível.",
            wishlist=wishlist,
            wishlist_index=wishlist_index,
            listing=listing,
        )

    existing = (
        db.query(WishlistTrackedListing)
        .filter(WishlistTrackedListing.wishlist_id == wishlist.id)
        .filter(WishlistTrackedListing.is_active.is_(True))
        .order_by(WishlistTrackedListing.slot.asc())
        .all()
    )

    automation_allowed = user_has_tracking_automation(db, user_id=user_id)

    for row in existing:
        if row.car_listing_id == listing.id:
            auto_txt = "ativadas" if row.price_drop_alert_enabled else "Premium"
            return _build_tracked_result(
                ok=False,
                status="already_tracked",
                message="Esse anúncio já está sendo rastreado nesta wishlist.",
                wishlist=wishlist,
                wishlist_index=wishlist_index,
                tracked=row,
                listing=listing,
                already_tracked=True,
                automation_enabled=bool(row.price_drop_alert_enabled),
            )

    plan_caps = get_plan_capabilities((get_user_plan_snapshot(db, user_id) or {}).get("plan_code"))

    total_tracked = (
        db.query(WishlistTrackedListing)
        .join(Wishlist, Wishlist.id == WishlistTrackedListing.wishlist_id)
        .filter(Wishlist.user_id == user_id)
        .filter(WishlistTrackedListing.is_active.is_(True))
        .count()
    )
    if total_tracked >= plan_caps.max_tracked_total:
        return _build_tracked_result(
            ok=False,
            status="plan_total_full",
            message=tracking_limit_message(plan_caps.max_tracked_total),
            wishlist=wishlist,
            wishlist_index=wishlist_index,
            listing=listing,
            automation_enabled=automation_allowed,
        )

    allowed_slots = min(MAX_TRACKED_PER_WISHLIST, plan_caps.max_tracked_slots_per_wishlist)

    if len(existing) >= allowed_slots:
        return _build_tracked_result(
            ok=False,
            status="slots_full",
            message="Você já rastreia 3 anúncios nesta wishlist. Remova um para adicionar outro.",
            wishlist=wishlist,
            wishlist_index=wishlist_index,
            listing=listing,
            automation_enabled=automation_allowed,
        )

    used_slots = {int(r.slot or 0) for r in existing}
    slot = 1
    while slot in used_slots and slot <= MAX_TRACKED_PER_WISHLIST:
        slot += 1

    tracked = WishlistTrackedListing(
        wishlist_id=wishlist.id,
        car_listing_id=listing.id,
        slot=slot,
        initial_price=listing.price,
        last_observed_price=listing.price,
        last_seen_at=listing.updated_at,
        listing_status=listing_status,
        price_drop_alert_enabled=automation_allowed,
    )
    db.add(tracked)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return _build_tracked_result(
            ok=False,
            status="already_tracked",
            message="Esse anúncio já está rastreado nessa wishlist.",
            wishlist=wishlist,
            wishlist_index=wishlist_index,
            listing=listing,
            slot=slot,
            already_tracked=True,
            automation_enabled=automation_allowed,
        )
    except Exception:
        db.rollback()
        return _build_tracked_result(
            ok=False,
            status="error",
            message="Não consegui rastrear este anúncio agora.",
            wishlist=wishlist,
            wishlist_index=wishlist_index,
            listing=listing,
            slot=slot,
            automation_enabled=automation_allowed,
        )
    invalidate_wishlist_summaries_cache(user_id)

    if automation_allowed:
        message = f"✅ Anúncio rastreado no slot {slot}/3.\nVou avisar se houver queda relevante de preço."
    else:
        message = (
            f"✅ Anúncio rastreado no slot {slot}/3.\n"
            f"Você pode acompanhar preço e status em:\n/wishlist_track_list {wishlist_index}\n\n"
            "Alertas automáticos de queda são Premium."
        )
    return _build_tracked_result(
        ok=True,
        status="added",
        message=message,
        wishlist=wishlist,
        wishlist_index=wishlist_index,
        tracked=tracked,
        listing=listing,
        slot=slot,
        automation_enabled=automation_allowed,
    )


def add_tracked_listing(db: Session, *, user_id, wishlist_index: int, listing_ref: str) -> tuple[bool, str]:
    result = add_tracked_listing_result(db, user_id=user_id, wishlist_index=wishlist_index, listing_ref=listing_ref)
    return result.ok, result.message


def get_tracking_capacity_snapshot(db: Session, wishlist_id) -> TrackingCapacitySnapshot:
    rows = (
        db.query(WishlistTrackedListing.slot)
        .filter(WishlistTrackedListing.wishlist_id == wishlist_id)
        .filter(WishlistTrackedListing.is_active.is_(True))
        .order_by(WishlistTrackedListing.slot.asc())
        .all()
    )
    used_slots = sorted({int(r[0]) for r in rows if r and r[0] is not None})
    free_slots = [s for s in range(1, MAX_TRACKED_PER_WISHLIST + 1) if s not in used_slots]
    return TrackingCapacitySnapshot(
        wishlist_id=str(wishlist_id),
        used_slots=used_slots,
        free_slots=free_slots,
        used_count=len(used_slots),
        max_slots=MAX_TRACKED_PER_WISHLIST,
        can_add=bool(free_slots),
    )


def list_tracked_listings(db: Session, *, user_id, wishlist_index: int) -> tuple[bool, str]:
    wishlist = _wishlist_from_index(db, user_id=user_id, wishlist_index=wishlist_index)
    if not wishlist:
        return False, "Wishlist não encontrada para você. Use /wishlist para listar os índices válidos."

    rows = (
        db.query(WishlistTrackedListing, CarListing)
        .outerjoin(CarListing, CarListing.id == WishlistTrackedListing.car_listing_id)
        .filter(WishlistTrackedListing.wishlist_id == wishlist.id)
        .filter(WishlistTrackedListing.is_active.is_(True))
        .order_by(WishlistTrackedListing.slot.asc())
        .all()
    )

    plan_caps = get_plan_capabilities((get_user_plan_snapshot(db, user_id) or {}).get("plan_code"))
    total_tracked = (
        db.query(WishlistTrackedListing)
        .join(Wishlist, Wishlist.id == WishlistTrackedListing.wishlist_id)
        .filter(Wishlist.user_id == user_id)
        .filter(WishlistTrackedListing.is_active.is_(True))
        .count()
    )
    lines: list[str] = [
        f"Busca {wishlist_index} — {wishlist.query}",
        f"Uso do plano: {total_tracked}/{plan_caps.max_tracked_total} rastreados",
    ]
    by_slot = {int(r.slot): (r, l) for r, l in rows}
    for slot in range(1, MAX_TRACKED_PER_WISHLIST + 1):
        pair = by_slot.get(slot)
        if pair is None:
            lines.append(f"\nSlot {slot} — vazio\nPara usar esse espaço, toque em ⭐ Rastrear em um anúncio.")
            continue
        row, listing = pair
        refresh_tracked_listing_snapshot(db, row, listing)
        if listing is None:
            lines.append(
                f"\nSlot {slot} — anúncio indisponível\n"
                "Status: indisponível\n"
                "Esse anúncio não está mais disponível na base, mas o histórico foi preservado."
            )
            continue
        label = _short_label(listing.title or listing.external_id or "Anúncio", max_len=70)
        ref = listing.external_id or "-"
        delta = None
        if row.initial_price is not None and row.last_observed_price is not None:
            delta = row.last_observed_price - row.initial_price
        if delta is None or delta == 0:
            var_txt = "Sem mudança de preço"
        else:
            pct = ""
            if row.initial_price and row.initial_price != 0:
                pct_val = (delta / row.initial_price) * Decimal("100")
                pct = f" ({pct_val:+.1f}%)".replace(".", ",")
            if delta < 0:
                var_txt = f"Caiu {_fmt_price(abs(delta))}{pct}"
            else:
                var_txt = f"Subiu {_fmt_price(abs(delta))}{pct}"
        status_map = {"active": "ativo", "inactive": "inativo/removido", "orphan": "indisponível"}
        status_txt = status_map.get(row.listing_status or "", "sem informação")
        notif_txt = "ativos" if row.price_drop_alert_enabled else "Premium"
        lines.append(
            f"\nSlot {slot} — {label}\n"
            f"Preço inicial: {_fmt_price(row.initial_price)}\n"
            f"Preço atual: {_fmt_price(row.last_observed_price)}\n"
            f"Variação: {var_txt}\n"
            f"Status: {status_txt}\n"
            f"Última vez visto: {_fmt_dt(row.last_seen_at)}\n"
            f"Alertas automáticos: {notif_txt}"
        )

    db.commit()
    lines.append("Use /wishlist_track_remove <n> <slot>")
    return True, "\n".join(lines)


def remove_tracked_listing(
    db: Session, *, user_id, wishlist_index: int, slot: int | None = None, car_listing_id: str | None = None
) -> tuple[bool, str]:
    wishlist = _wishlist_from_index(db, user_id=user_id, wishlist_index=wishlist_index)
    if not wishlist:
        return False, "Wishlist não encontrada para você. Use /wishlist para listar os índices válidos."

    if slot is None and not car_listing_id:
        return False, "Informe um slot ou identificador do anúncio para remover."

    row = None
    if slot is not None:
        if slot < 1 or slot > MAX_TRACKED_PER_WISHLIST:
            return False, f"Slot inválido. Use um valor entre 1 e {MAX_TRACKED_PER_WISHLIST}."
        row = (
            db.query(WishlistTrackedListing)
            .filter(WishlistTrackedListing.wishlist_id == wishlist.id)
            .filter(WishlistTrackedListing.is_active.is_(True))
            .filter(WishlistTrackedListing.slot == slot)
            .first()
        )
    elif car_listing_id:
        import uuid
        try:
            listing_uuid = uuid.UUID(str(car_listing_id))
        except Exception:
            return False, "Identificador de anúncio inválido."
        row = (
            db.query(WishlistTrackedListing)
            .filter(WishlistTrackedListing.wishlist_id == wishlist.id)
            .filter(WishlistTrackedListing.is_active.is_(True))
            .filter(WishlistTrackedListing.car_listing_id == listing_uuid)
            .first()
        )

    if not row:
        if slot is not None:
            return False, "Não há anúncio rastreado nesse slot."
        return False, "Esse anúncio não está sendo rastreado nesta wishlist."

    row.is_active = False
    db.add(row)
    db.commit()
    invalidate_wishlist_summaries_cache(user_id)
    return True, f"Rastreamento removido do slot {row.slot}. Use /wishlist_track_list <n> para conferir."


def set_price_drop_alert_enabled(db: Session, *, user_id, wishlist_index: int, slot: int, enabled: bool) -> tuple[bool, str]:
    wishlist = _wishlist_from_index(db, user_id=user_id, wishlist_index=wishlist_index)
    if not wishlist:
        return False, "Wishlist não encontrada para você. Use /wishlist para listar os índices válidos."
    if slot < 1 or slot > MAX_TRACKED_PER_WISHLIST:
        return False, f"Slot inválido. Use um valor entre 1 e {MAX_TRACKED_PER_WISHLIST}."
    row = (
        db.query(WishlistTrackedListing)
        .filter(WishlistTrackedListing.wishlist_id == wishlist.id)
        .filter(WishlistTrackedListing.is_active.is_(True))
        .filter(WishlistTrackedListing.slot == slot)
        .first()
    )
    if not row:
        return False, "Slot sem anúncio rastreado. Use /wishlist_track_list <n> para conferir."
    row.price_drop_alert_enabled = bool(enabled)
    if not enabled:
        row.last_price_drop_alert_at = None
        row.last_price_drop_alert_price = None
    db.commit()
    if enabled:
        return True, f"Notificações automáticas ativadas para o slot {slot}."
    return True, f"Notificações automáticas desativadas para o slot {slot}."
