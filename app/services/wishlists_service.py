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
    "icarros",
    "mobiauto",
    "kavak",
    "facebook_marketplace",
}

# Aceita:
#  - "até 2004" / "ate 2004" / "ano<=2004"
#  - "a partir de 2014" / "ano>=2014"
#  - "entre 2014 e 2020" / "2014 até 2020" / "2014-2020"
_YEAR_MAX_PATTERNS = [
    re.compile(r"(?:\bate\b|\baté\b)\s+(\d{4})", re.IGNORECASE),
    re.compile(r"(?:\bate\b|\baté\b)\s+ano\s+(\d{4})", re.IGNORECASE),
    re.compile(r"\bano\s*(?:<=|=<|≤)\s*(\d{4})", re.IGNORECASE),
    re.compile(r"\byear\s*(?:<=|=<|≤)\s*(\d{4})", re.IGNORECASE),
]

_YEAR_MIN_PATTERNS = [
    re.compile(r"\b(?:a\s+partir\s+de|apartir\s+de|desde)\s+(\d{4})\b", re.IGNORECASE),
    re.compile(r"\bano\s*(?:>=|=>|≥)\s*(\d{4})\b", re.IGNORECASE),
    re.compile(r"\byear\s*(?:>=|=>|≥)\s*(\d{4})\b", re.IGNORECASE),
]

_YEAR_RANGE_PATTERNS = [
    re.compile(r"\bentre\s+(\d{4})\s+e\s+(\d{4})\b", re.IGNORECASE),
    re.compile(r"\bde\s+(\d{4})\s+a\s+(\d{4})\b", re.IGNORECASE),
    re.compile(r"\b(\d{4})\s*(?:\bate\b|\baté\b)\s*(\d{4})\b", re.IGNORECASE),
    re.compile(r"\b(\d{4})\s*(?:-|–|—)\s*(\d{4})\b", re.IGNORECASE),
]


# Aceita diretivas de preço (BRL) embutidas na query:
#  - "entre 200k e 300k" / "200k-300k" / "de R$ 80.000 a R$ 120.000"
#  - "a partir de 80k" / "até 120k"
#  - "preço<=120k" / "valor >= 100000"
_PRICE_RANGE_PATTERNS = [
    re.compile(
        r"\bentre\s+(?:r\$\s*)?([0-9\.,]+\s*[kKmM]?)\s+e\s+(?:r\$\s*)?([0-9\.,]+\s*[kKmM]?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bde\s+(?:r\$\s*)?([0-9\.,]+\s*[kKmM]?)\s+a\s+(?:r\$\s*)?([0-9\.,]+\s*[kKmM]?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b([0-9\.,]+\s*[kKmM]?)\s*(?:-|–|—)\s*([0-9\.,]+\s*[kKmM]?)\b",
        re.IGNORECASE,
    ),
]

_PRICE_MAX_PATTERNS = [
    re.compile(
        r"\b(?:ate|até)\s+(?:r\$\s*)?([0-9\.,]+\s*[kKmM]?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:preco|preço|valor|price)\s*(?:<=|=<|≤)\s*(?:r\$\s*)?([0-9\.,]+\s*[kKmM]?)\b",
        re.IGNORECASE,
    ),
]

_PRICE_MIN_PATTERNS = [
    re.compile(
        r"\b(?:a\s+partir\s+de|apartir\s+de|desde)\s+(?:r\$\s*)?([0-9\.,]+\s*[kKmM]?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:preco|preço|valor|price)\s*(?:>=|=>|≥)\s*(?:r\$\s*)?([0-9\.,]+\s*[kKmM]?)\b",
        re.IGNORECASE,
    ),
]


def _parse_human_money_to_int(raw: str) -> Optional[int]:
    """Converte valores do tipo '200k', '1.2m', '120.000', 'R$ 80.000' em inteiro (centavos ignorados).

    Regras:
      - 'k' = mil, 'm' = milhão
      - aceita '.' ou ',' como separadores (pt-BR)
      - decimais são ignorados (tratamos como unidade inteira de BRL)
    """
    if not raw:
        return None

    s = raw.strip().lower()
    s = s.replace("r$", "").strip()
    s = re.sub(r"\s+", "", s)

    mult = 1
    if s.endswith("k"):
        mult = 1_000
        s = s[:-1]
    elif s.endswith("m"):
        mult = 1_000_000
        s = s[:-1]

    # normaliza: remove milhares e mantém decimal como '.' (se existir)
    # Ex: '120.000' -> '120000'
    # Ex: '1.2' -> '1.2'
    # Ex: '1,2' -> '1.2'
    s = s.replace(".", "") if re.search(r"\d\.\d{3}", s) else s
    s = s.replace(",", ".")

    # remove qualquer lixo restante
    s = re.sub(r"[^0-9\.]+", "", s)
    if not s:
        return None

    try:
        num = float(s)
    except Exception:
        return None

    if num <= 0:
        return None

    val = int(round(num * mult))
    if val <= 0:
        return None
    return val


def _is_plausible_price(v: int) -> bool:
    # compatível com NUMERIC(12,2): valor absoluto < 10^10 (R$ 9.999.999.999)
    return 1 <= v <= 9_999_999_999


def _extract_price_directives(query: str) -> Tuple[str, Optional[int], Optional[int]]:
    """Extrai diretivas de preço (min/max/range) e limpa a query.

    Exemplos:
      - "audi a6 entre 200k e 300k"  -> price_min=200000, price_max=300000
      - "civic até 90k"             -> price_max=90000
      - "preço>=80k"                -> price_min=80000
      - "R$ 80.000 a R$ 120.000"    -> price_min=80000, price_max=120000
    """
    q = (query or "").strip()
    if not q:
        return q, None, None

    pmin: Optional[int] = None
    pmax: Optional[int] = None

    # Range primeiro
    for rx in _PRICE_RANGE_PATTERNS:
        m = rx.search(q)
        if not m:
            continue

        v1 = _parse_human_money_to_int(m.group(1) or "")
        v2 = _parse_human_money_to_int(m.group(2) or "")
        if not v1 or not v2:
            continue
        if not (_is_plausible_price(v1) and _is_plausible_price(v2)):
            continue

        pmin, pmax = (v1, v2) if v1 <= v2 else (v2, v1)
        q = _clean_span(q, m.start(), m.end())
        break

    # Max
    if pmax is None:
        for rx in _PRICE_MAX_PATTERNS:
            m = rx.search(q)
            if not m:
                continue
            raw = (m.group(1) or "").strip()
            v = _parse_human_money_to_int(raw)

            # evita confundir "até 2020" com preço
            if v is None and raw.isdigit() and len(raw) == 4:
                continue

            if v and _is_plausible_price(v):
                pmax = v
                q = _clean_span(q, m.start(), m.end())
                break

    # Min
    if pmin is None:
        for rx in _PRICE_MIN_PATTERNS:
            m = rx.search(q)
            if not m:
                continue
            raw = (m.group(1) or "").strip()
            v = _parse_human_money_to_int(raw)
            if v and _is_plausible_price(v):
                pmin = v
                q = _clean_span(q, m.start(), m.end())
                break

    return q, pmin, pmax


def _clean_span(q: str, start: int, end: int) -> str:
    q = (q[:start] + " " + q[end:]).strip()
    q = re.sub(r"\s+", " ", q).strip()
    return q


def _extract_year_directives(query: str) -> Tuple[str, Optional[int], Optional[int]]:
    """Extrai diretivas de ano (min/max/range) e limpa a query.

    Exemplos:
      - "audi a6 entre 2014 e 2020"  -> year_min=2014, year_max=2020
      - "civic 1993 até 2004"       -> year_min=1993, year_max=2004
      - "defender até 2004"         -> year_max=2004
      - "civic a partir de 2014"    -> year_min=2014
    """
    q = (query or "").strip()
    if not q:
        return q, None, None

    year_min: Optional[int] = None
    year_max: Optional[int] = None

    # Range primeiro (mais específico)
    for rx in _YEAR_RANGE_PATTERNS:
        m = rx.search(q)
        if not m:
            continue
        try:
            y1 = int(m.group(1))
            y2 = int(m.group(2))
        except Exception:
            y1 = y2 = None
        if y1 and y2 and 1900 <= y1 <= 2100 and 1900 <= y2 <= 2100:
            year_min, year_max = (y1, y2) if y1 <= y2 else (y2, y1)
            q = _clean_span(q, m.start(), m.end())
            break

    # Max
    if year_max is None:
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
                q = _clean_span(q, m.start(), m.end())
                break

    # Min
    if year_min is None:
        for rx in _YEAR_MIN_PATTERNS:
            m = rx.search(q)
            if not m:
                continue
            try:
                y = int(m.group(1))
            except Exception:
                y = None
            if y and 1900 <= y <= 2100:
                year_min = y
                q = _clean_span(q, m.start(), m.end())
                break

    return q, year_min, year_max

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
    """Cria wishlist e opcionalmente cria filtros de ano (gte/lte) se diretivas existirem.

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

    # 1) Ano (range/min/max)
    cleaned_query, year_min, year_max = _extract_year_directives(query)
    # 2) Preço (range/min/max) — roda em cima da query já limpa de diretivas de ano
    cleaned_query, price_min, price_max = _extract_price_directives(cleaned_query)

    cleaned_query = (cleaned_query or "").strip()
    if not cleaned_query:
        return False, "Query inválida. Ex: /wishlist_add audi a6 entre 2014 e 2020"

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

    
    # auto-filtros (quando houver diretivas)
    filters = []
    if year_min:
        filters.append(WishlistFilter(wishlist_id=w.id, field="year", operator="gte", value=str(year_min)))
    if year_max:
        filters.append(WishlistFilter(wishlist_id=w.id, field="year", operator="lte", value=str(year_max)))

    if price_min:
        filters.append(WishlistFilter(wishlist_id=w.id, field="price", operator="gte", value=str(price_min)))
    if price_max:
        filters.append(WishlistFilter(wishlist_id=w.id, field="price", operator="lte", value=str(price_max)))

    if filters:
        db.add_all(filters)
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