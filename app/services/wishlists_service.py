import uuid
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.wishlist import Wishlist
from app.models.wishlist_filter import WishlistFilter

MAX_WISHLISTS_PER_USER = 3


def list_wishlists(db: Session, user_id):
    return (
        db.query(Wishlist)
        .filter(Wishlist.user_id == user_id)
        .order_by(Wishlist.created_at.asc())
        .all()
    )


def add_wishlist(db: Session, user_id, query: str):
    count = db.query(func.count(Wishlist.id)).filter(Wishlist.user_id == user_id).scalar() or 0
    if count >= MAX_WISHLISTS_PER_USER:
        return False, f"Limite atingido: {MAX_WISHLISTS_PER_USER} wishlists por usuário."

    w = Wishlist(id=uuid.uuid4(), user_id=user_id, query=query.strip(), is_active=True)
    db.add(w)
    db.commit()
    return True, "Wishlist criada."


def remove_wishlist(db: Session, user_id, index: int):
    wishlists = list_wishlists(db, user_id)
    if index < 1 or index > len(wishlists):
        return False, "Número inválido. Use /wishlist listar."

    w = wishlists[index - 1]
    db.delete(w)
    db.commit()
    return True, "Wishlist removida."


def add_filter(db: Session, wishlist_id, field: str, operator: str, value: str):
    # MVP: só aceita price e source
    field = field.strip().lower()
    operator = operator.strip().lower()
    value = value.strip().lower()

    if field not in ("price", "source"):
        return False, "Campo inválido. Use: price | source"

    if field == "price" and operator not in ("lt", "lte", "gt", "gte", "eq", "neq"):
        return False, "Operador inválido para price. Use: lt|lte|gt|gte|eq|neq"

    if field == "source" and operator not in ("eq", "neq"):
        return False, "Operador inválido para source. Use: eq|neq"

    if field == "source" and value not in ("mercadolivre", "olx"):
        return False, "Valor inválido para source. Use: mercadolivre | olx"

    row = WishlistFilter(wishlist_id=wishlist_id, field=field, operator=operator, value=value)
    db.add(row)
    try:
        db.commit()
        return True, "Filtro adicionado."
    except Exception:
        db.rollback()
        return False, "Filtro já existe (duplicado) ou erro ao salvar."


def list_filters(db: Session, wishlist_id):
    return (
        db.query(WishlistFilter)
        .filter(WishlistFilter.wishlist_id == wishlist_id)
        .order_by(WishlistFilter.created_at.asc())
        .all()
    )


def remove_filter(db: Session, wishlist_id, index: int):
    filters = list_filters(db, wishlist_id)
    if index < 1 or index > len(filters):
        return False, "Número inválido. Use /wishlist filter list <n>"

    f = filters[index - 1]
    db.delete(f)
    db.commit()
    return True, "Filtro removido."
