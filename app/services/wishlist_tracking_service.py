from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.car_listing import CarListing
from app.models.wishlist import Wishlist
from app.models.wishlist_tracked_listing import WishlistTrackedListing

MAX_TRACKED_PER_WISHLIST = 3


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
    ref = (listing_ref or "").strip()
    if not ref:
        return None

    row = db.query(CarListing).filter(CarListing.external_id == ref).order_by(CarListing.created_at.desc()).first()
    if row:
        return row

    row = db.query(CarListing).filter(CarListing.url == ref).order_by(CarListing.created_at.desc()).first()
    return row


def _short_label(value: Any, max_len: int = 80) -> str:
    txt = str(value or "").strip()
    if len(txt) <= max_len:
        return txt
    return txt[: max_len - 1].rstrip() + "…"


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
        )
    )
    db.commit()

    title = _short_label(listing.title or "Anúncio")
    return True, f"Rastreamento ativado na wishlist {wishlist_index} (slot {slot}/{MAX_TRACKED_PER_WISHLIST}): {title}"


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
        if listing is None:
            lines.append(f"{row.slot}. anúncio indisponível (registro removido)")
            continue
        label = _short_label(listing.title or listing.external_id or "Anúncio", max_len=70)
        ref = listing.external_id or "-"
        lines.append(f"{row.slot}. {label} [id:{ref}]")

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
