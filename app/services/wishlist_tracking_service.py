from __future__ import annotations

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

MAX_TRACKED_PER_WISHLIST = 3


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
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _listing_status(listing: CarListing | None) -> str:
    if listing is None:
        return "orphan"
    if getattr(listing, "is_sold", False):
        return "inactive"
    return "active"


def refresh_tracked_listing_snapshot(
    db: Session, tracked: WishlistTrackedListing, listing: CarListing | None = None
) -> dict[str, Any]:
    listing_row = listing
    if listing_row is None and tracked.car_listing_id:
        listing_row = db.query(CarListing).filter(CarListing.id == tracked.car_listing_id).first()

    if listing_row is None:
        tracked.listing_status = "orphan"
        return {"status": "orphan", "direction": None}

    current_price = listing_row.price
    previous_price = tracked.last_observed_price

    direction = "unchanged"
    if current_price is not None and previous_price is not None:
        if current_price < previous_price:
            direction = "dropped"
        elif current_price > previous_price:
            direction = "increased"

    if current_price is not None and previous_price is not None and current_price != previous_price:
        delta = current_price - previous_price
        tracked.last_price_change_amount = delta
        if previous_price != 0:
            tracked.last_price_change_pct = delta / previous_price
        tracked.last_price_change_direction = direction
        tracked.last_price_change_at = datetime.now(timezone.utc)

    if current_price is not None:
        tracked.last_observed_price = current_price
    if tracked.initial_price is None and current_price is not None:
        tracked.initial_price = current_price

    tracked.last_seen_at = listing_row.updated_at or tracked.last_seen_at
    tracked.listing_status = _listing_status(listing_row)
    return {"status": tracked.listing_status, "direction": direction}


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


def add_tracked_listing(db: Session, *, user_id, wishlist_index: int, listing_ref: str) -> tuple[bool, str]:
    wishlist = _wishlist_from_index(db, user_id=user_id, wishlist_index=wishlist_index)
    if not wishlist:
        return False, "Wishlist não encontrada para você. Use /wishlist para listar os índices válidos."

    listing = _find_listing(db, listing_ref)
    if not listing:
        return False, "Não encontrei esse anúncio no AutoHunter. Tente external_id exato ou URL já ingerida."

    existing = (
        db.query(WishlistTrackedListing)
        .filter(WishlistTrackedListing.wishlist_id == wishlist.id)
        .order_by(WishlistTrackedListing.slot.asc())
        .all()
    )

    for row in existing:
        if row.car_listing_id == listing.id:
            return False, "Esse anúncio já está rastreado nessa wishlist. Use /wishlist_track_list para ver os slots."

    if len(existing) >= MAX_TRACKED_PER_WISHLIST:
        return (
            False,
            f"Limite atingido ({MAX_TRACKED_PER_WISHLIST}/{MAX_TRACKED_PER_WISHLIST}). "
            "Remova um slot com /wishlist_track_remove <n> <slot>.",
        )

    used_slots = {int(r.slot or 0) for r in existing}
    slot = 1
    while slot in used_slots and slot <= MAX_TRACKED_PER_WISHLIST:
        slot += 1

    db.add(
        WishlistTrackedListing(
            wishlist_id=wishlist.id,
            car_listing_id=listing.id,
            slot=slot,
            initial_price=listing.price,
            last_observed_price=listing.price,
            last_seen_at=listing.updated_at,
            listing_status=_listing_status(listing),
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return False, "Esse anúncio já está rastreado nessa wishlist."

    title = (listing.title or "Anúncio").strip()
    return (
        True,
        f"Rastreamento ativado (slot {slot}/{MAX_TRACKED_PER_WISHLIST}): {title[:80]}. "
        f"Preço atual: {_fmt_price(listing.price)}.",
    )


def list_tracked_listings(db: Session, *, user_id, wishlist_index: int) -> tuple[bool, str]:
    wishlist = _wishlist_from_index(db, user_id=user_id, wishlist_index=wishlist_index)
    if not wishlist:
        return False, "Wishlist não encontrada para você. Use /wishlist para listar os índices válidos."

    rows = (
        db.query(WishlistTrackedListing, CarListing)
        .outerjoin(CarListing, CarListing.id == WishlistTrackedListing.car_listing_id)
        .filter(WishlistTrackedListing.wishlist_id == wishlist.id)
        .order_by(WishlistTrackedListing.slot.asc())
        .all()
    )

    if not rows:
        return True, "Sem anúncios rastreados nessa wishlist. Use /wishlist_track_add <n> <url|external_id>."

    lines: list[str] = [f"📌 Rastreados da wishlist {wishlist_index}: {wishlist.query}"]
    for row, listing in rows:
        refresh_tracked_listing_snapshot(db, row, listing)
        if listing is None:
            lines.append(f"{row.slot}. anúncio indisponível (registro removido)")
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
        status_map = {"active": "ativo", "inactive": "inativo", "orphan": "inativo/removido"}
        status_txt = status_map.get(row.listing_status or "", "sem informação")
        lines.append(
            f"{row.slot}. {label} [id:{ref}]\n"
            f"   Atual: {_fmt_price(row.last_observed_price)} | Inicial: {_fmt_price(row.initial_price)}\n"
            f"   {var_txt} | Status: {status_txt} | Visto: {_fmt_dt(row.last_seen_at)}\n"
            f"   Alerta de queda: {'ligado' if row.price_drop_alert_enabled else 'desligado'}"
        )

    db.commit()
    lines.append("Use /wishlist_track_remove <n> <slot>")
    return True, "\n".join(lines)


def remove_tracked_listing(db: Session, *, user_id, wishlist_index: int, slot: int) -> tuple[bool, str]:
    wishlist = _wishlist_from_index(db, user_id=user_id, wishlist_index=wishlist_index)
    if not wishlist:
        return False, "Wishlist não encontrada para você. Use /wishlist para listar os índices válidos."

    if slot < 1 or slot > MAX_TRACKED_PER_WISHLIST:
        return False, f"Slot inválido. Use um valor entre 1 e {MAX_TRACKED_PER_WISHLIST}."

    row = (
        db.query(WishlistTrackedListing)
        .filter(WishlistTrackedListing.wishlist_id == wishlist.id)
        .filter(WishlistTrackedListing.slot == slot)
        .first()
    )
    if not row:
        return False, "Esse slot já está vazio. Confira os slots com /wishlist_track_list <n>."

    db.delete(row)
    db.commit()
    return True, f"Rastreamento removido do slot {slot}. Use /wishlist_track_list <n> para conferir."


def set_price_drop_alert_enabled(db: Session, *, user_id, wishlist_index: int, slot: int, enabled: bool) -> tuple[bool, str]:
    wishlist = _wishlist_from_index(db, user_id=user_id, wishlist_index=wishlist_index)
    if not wishlist:
        return False, "Wishlist não encontrada para você. Use /wishlist para listar os índices válidos."
    if slot < 1 or slot > MAX_TRACKED_PER_WISHLIST:
        return False, f"Slot inválido. Use um valor entre 1 e {MAX_TRACKED_PER_WISHLIST}."
    row = (
        db.query(WishlistTrackedListing)
        .filter(WishlistTrackedListing.wishlist_id == wishlist.id)
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
        return True, f"Alerta de queda de preço ativado para o slot {slot}."
    return True, f"Alerta de queda de preço desativado para o slot {slot}."
