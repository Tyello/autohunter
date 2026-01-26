from __future__ import annotations

import re
import uuid
from typing import Optional, Tuple, Dict, Any

from sqlalchemy.orm import Session
from sqlalchemy import func, text

from app.models.wishlist import Wishlist
from app.models.wishlist_filter import WishlistFilter

# Fallback (quando não existir plano/assinatura no banco ainda)
DEFAULT_MAX_WISHLISTS_PER_USER = 3

# Fontes conhecidas hoje (expanda sem medo)
KNOWN_SOURCES = {
    "mercadolivre",
    "olx",
    "webmotors",
    "chavesnamao",
    "gogarage",
}

_YEAR_MAX_PATTERNS = [
    re.compile(r"(?:\bate\b|\baté\b)\s+ano\s+(\d{4})", re.IGNORECASE),
    re.compile(r"\bano\s*(?:<=|=<|≤)\s*(\d{4})", re.IGNORECASE),
    re.compile(r"\byear\s*(?:<=|=<|≤)\s*(\d{4})", re.IGNORECASE),
]


def _extract_year_max_directive(query: str) -> Tuple[str, Optional[int]]:
    """Suporta sintaxes amigáveis no /wishlist_add:

    - "daihatsu cuore até 2005"
    - "daihatsu cuore ano<=2005"
    - "daihatsu cuore year<=2005"

    Retorna (query_limpa, year_max).
    """
    q = (query or "").strip()
    if not q:
        return q, None

    year_max: Optional[int] = None
    for rx in _YEAR_MAX_PATTERNS:
        m = rx.search(q)
        if not m:
            continue
        try:
            y = int(m.group(1))
        except Exception:
            y = None
        if y and 1900 <= y <= 2100:
            year_max = y
            q = (q[: m.start()] + " " + q[m.end() :]).strip()
            q = re.sub(r"\s+", " ", q).strip()
            break

    return q, year_max


def get_user_plan_snapshot(db: Session, user_id) -> Dict[str, Any]:
    """Busca limites do plano no banco (sem depender do model Subscription).

    Tenta 2 caminhos, porque o seu schema pode usar:
      A) subscriptions.user_id
      B) subscriptions.account_id (e users.account_id)

    Estrutura esperada:
      plans(id, code, daily_alert_limit, max_wishlists)
      subscriptions(plan_id, user_id|account_id, is_active, created_at)
      users(id, account_id)

    Se não existir/der erro, retorna fallback.
    """
    snap = {
        "plan_code": "free",
        "max_wishlists": DEFAULT_MAX_WISHLISTS_PER_USER,
        "daily_alert_limit": None,
    }

    def _apply_row(row):
        if not row:
            return
        snap["plan_code"] = row.get("plan_code") or snap["plan_code"]
        mw = row.get("max_wishlists")
        dal = row.get("daily_alert_limit")
        if mw is not None:
            snap["max_wishlists"] = int(mw)
        if dal is not None:
            snap["daily_alert_limit"] = int(dal)

    # 1) Caminho direto por user_id
    try:
        row = (
            db.execute(
                text(
                    """
                    SELECT p.code AS plan_code, p.max_wishlists AS max_wishlists, p.daily_alert_limit AS daily_alert_limit
                    FROM subscriptions s
                    JOIN plans p ON p.id = s.plan_id
                    WHERE s.user_id = :uid
                      AND (s.is_active IS TRUE)
                    ORDER BY s.created_at DESC
                    LIMIT 1
                    """
                ),
                {"uid": user_id},
            )
            .mappings()
            .first()
        )
        _apply_row(row)
    except Exception:
        pass

    # 2) Caminho por account_id (quando subscriptions não tem user_id)
    if snap["max_wishlists"] == DEFAULT_MAX_WISHLISTS_PER_USER and snap["plan_code"] == "free":
        try:
            row = (
                db.execute(
                    text(
                        """
                        SELECT p.code AS plan_code, p.max_wishlists AS max_wishlists, p.daily_alert_limit AS daily_alert_limit
                        FROM users u
                        JOIN subscriptions s ON s.account_id = u.account_id
                        JOIN plans p ON p.id = s.plan_id
                        WHERE u.id = :uid
                          AND (s.is_active IS TRUE)
                        ORDER BY s.created_at DESC
                        LIMIT 1
                        """
                    ),
                    {"uid": user_id},
                )
                .mappings()
                .first()
            )
            _apply_row(row)
        except Exception:
            pass

    return snap


def get_max_wishlists_for_user(db: Session, user_id) -> int:
    return int(get_user_plan_snapshot(db, user_id).get("max_wishlists") or DEFAULT_MAX_WISHLISTS_PER_USER)


def list_wishlists(db: Session, user_id):
    return (
        db.query(Wishlist)
        .filter(Wishlist.user_id == user_id)
        .order_by(Wishlist.created_at.asc())
        .all()
    )


def add_wishlist(db: Session, user_id, query: str):
    # limite por plano
    max_wishlists = get_max_wishlists_for_user(db, user_id)
    count = db.query(func.count(Wishlist.id)).filter(Wishlist.user_id == user_id).scalar() or 0
    if count >= max_wishlists:
        return False, f"Limite atingido: {max_wishlists} wishlists no seu plano."

    # suporte a diretiva amigável: "até 2005"
    cleaned_query, year_max = _extract_year_max_directive(query)

    w = Wishlist(id=uuid.uuid4(), user_id=user_id, query=cleaned_query.strip(), is_active=True)
    db.add(w)
    db.commit()

    # auto-filtro de ano
    if year_max:
        row = WishlistFilter(wishlist_id=w.id, field="year", operator="lte", value=str(year_max))
        db.add(row)
        try:
            db.commit()
        except Exception:
            db.rollback()

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
    """Filtros por wishlist.

    Campos suportados:
      - price  (comparadores numéricos)
      - year   (comparadores numéricos)
      - source (eq/neq)

    Operadores:
      - price/year: lt|lte|gt|gte|eq|neq
      - source: eq|neq
    """
    field = (field or "").strip().lower()
    operator = (operator or "").strip().lower()
    value = (value or "").strip()

    if field not in ("price", "source", "year"):
        return False, "Campo inválido. Use: price | year | source"

    if field in ("price", "year") and operator not in ("lt", "lte", "gt", "gte", "eq", "neq"):
        return False, f"Operador inválido para {field}. Use: lt|lte|gt|gte|eq|neq"

    if field == "source" and operator not in ("eq", "neq"):
        return False, "Operador inválido para source. Use: eq|neq"

    if field == "source":
        v = value.strip().lower()
        if v not in KNOWN_SOURCES:
            return False, "Valor inválido para source. Use: " + " | ".join(sorted(KNOWN_SOURCES))
        value = v

    if field == "year":
        try:
            y = int(value)
        except Exception:
            return False, "Ano inválido. Ex: year lte 2005"
        if y < 1900 or y > 2100:
            return False, "Ano fora do intervalo (1900-2100)."
        value = str(y)

    # price: aceita int/decimal/pt-BR (validação real acontece no matching)
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
        return False, "Número inválido. Use /wishlist_filter_list <n>"

    f = filters[index - 1]
    db.delete(f)
    db.commit()
    return True, "Filtro removido."
