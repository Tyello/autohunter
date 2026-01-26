from __future__ import annotations

import re
import uuid
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.plan import Plan
from app.models.subscription import Subscription
from app.models.user import User
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

# Aceita "até 2004" / "ate 2004" / "até ano 2004" / "ano<=2004"
_YEAR_MAX_PATTERNS = [
    re.compile(r"(?:\bate\b|\baté\b)\s+(\d{4})", re.IGNORECASE),
    re.compile(r"(?:\bate\b|\baté\b)\s+ano\s+(\d{4})", re.IGNORECASE),
    re.compile(r"\bano\s*(?:<=|=<|≤)\s*(\d{4})", re.IGNORECASE),
    re.compile(r"\byear\s*(?:<=|=<|≤)\s*(\d{4})", re.IGNORECASE),
]


def _extract_year_max_directive(query: str) -> Tuple[str, Optional[int]]:
    """Extrai uma diretiva de ano máximo e limpa a query.

    Exemplos:
      - "defender até 2004"
      - "defender até ano 2004"
      - "defender ano<=2004"

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
    """Retorna um snapshot dos limites do plano do usuário.

    Padrão do seu schema (conforme users_service):
      User.account_id -> Subscription(account_id, status) -> Plan(max_wishlists, daily_alert_limit)

    Fallback: FREE com max_wishlists=3.
    """
    snap: Dict[str, Any] = {
        "plan_code": "free",
        "max_wishlists": DEFAULT_MAX_WISHLISTS_PER_USER,
        "daily_alert_limit": None,
    }

    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return snap

        q = db.query(Subscription)

        # Preferência: subscriptions por account_id
        if hasattr(Subscription, "account_id") and getattr(user, "account_id", None) is not None:
            q = q.filter(Subscription.account_id == user.account_id)
        # Alternativa: caso exista subscriptions.user_id (alguns schemas)
        elif hasattr(Subscription, "user_id"):
            q = q.filter(Subscription.user_id == user_id)
        else:
            return snap

        # Ativo
        if hasattr(Subscription, "status"):
            q = q.filter(Subscription.status == "active")
        elif hasattr(Subscription, "is_active"):
            q = q.filter(Subscription.is_active.is_(True))

        # Ordenação
        if hasattr(Subscription, "created_at"):
            q = q.order_by(Subscription.created_at.desc())
        else:
            q = q.order_by(Subscription.id.desc())

        sub = q.first()
        if not sub:
            return snap

        plan = db.query(Plan).filter(Plan.id == sub.plan_id).first() if getattr(sub, "plan_id", None) else None
        if not plan:
            return snap

        snap["plan_code"] = getattr(plan, "code", "free") or "free"
        mw = getattr(plan, "max_wishlists", None)
        if mw is not None:
            snap["max_wishlists"] = int(mw)
        dal = getattr(plan, "daily_alert_limit", None)
        if dal is not None:
            snap["daily_alert_limit"] = int(dal)

        return snap

    except Exception:
        # Se qualquer coisa der errado, mantém fallback (não explode o bot)
        try:
            db.rollback()
        except Exception:
            pass
        return snap


def get_max_wishlists_for_user(db: Session, user_id) -> int:
    snap = get_user_plan_snapshot(db, user_id)
    return int(snap.get("max_wishlists") or DEFAULT_MAX_WISHLISTS_PER_USER)


def list_wishlists(db: Session, user_id):
    return (
        db.query(Wishlist)
        .filter(Wishlist.user_id == user_id)
        .order_by(Wishlist.created_at.asc())
        .all()
    )


def add_wishlist(db: Session, user_id, query: str):
    """Cria wishlist e opcionalmente cria filtro de ano (lte) se a diretiva existir.

    Importante: faz rollback preventivo para não herdar transação abortada.
    """
    # Limpa transação abortada anterior (evita InFailedSqlTransaction)
    try:
        db.rollback()
    except Exception:
        pass

    max_wishlists = get_max_wishlists_for_user(db, user_id)
    count = db.query(func.count(Wishlist.id)).filter(Wishlist.user_id == user_id).scalar() or 0
    if count >= max_wishlists:
        return False, f"Limite atingido: {max_wishlists} wishlists no seu plano."

    cleaned_query, year_max = _extract_year_max_directive(query)
    cleaned_query = (cleaned_query or "").strip()
    if not cleaned_query:
        return False, "Query inválida. Ex: /wishlist add defender até 2004"

    w = Wishlist(id=uuid.uuid4(), user_id=user_id, query=cleaned_query, is_active=True)
    db.add(w)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return False, "Erro ao salvar wishlist (conflito/duplicidade)."
    except SQLAlchemyError:
        db.rollback()
        return False, "Erro ao salvar wishlist. Tente novamente."

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
    try:
        db.commit()
    except Exception:
        db.rollback()
        return False, "Erro ao remover wishlist."
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