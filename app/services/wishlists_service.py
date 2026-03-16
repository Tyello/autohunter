from __future__ import annotations

import re
import uuid
import logging
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import delete, func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.plan import Plan
from app.models.subscription import Subscription
from app.models.user import User
from app.models.wishlist import Wishlist
from app.models.wishlist_filter import WishlistFilter
from app.models.wishlist_listing_activity import WishlistListingActivity
from app.models.wishlist_token import WishlistToken
from app.services.source_execution_service import run_source_for_all_wishlists
from app.services.system_logs_service import log
from app.services.wishlist_sources_service import allowed_sources_for_wishlists
from app.services.wishlist_tokens_service import rebuild_tokens_for_wishlist


logger = logging.getLogger(__name__)

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

KNOWN_STATES = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG",
    "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
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
    """Converte valores do tipo '200k', '1.2m', '120.000', 'R$ 80.000' em inteiro (centavos ignorados)."""
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

    s = s.replace(".", "") if re.search(r"\d\.\d{3}", s) else s
    s = s.replace(",", ".")
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
    return val if val > 0 else None


def _is_plausible_price(v: int) -> bool:
    return 1 <= v <= 9_999_999_999


def _clean_span(q: str, start: int, end: int) -> str:
    q = (q[:start] + " " + q[end:]).strip()
    q = re.sub(r"\s+", " ", q).strip()
    return q


def _extract_price_directives(query: str) -> Tuple[str, Optional[int], Optional[int]]:
    q = (query or "").strip()
    if not q:
        return q, None, None

    pmin: Optional[int] = None
    pmax: Optional[int] = None

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


def _extract_year_directives(query: str) -> Tuple[str, Optional[int], Optional[int]]:
    """Extrai diretivas de ano (min/max/range) e limpa a query.

    **Contrato importante:**
    - "entre 2014 e 2015" => year_min=2014, year_max=2015 (INCLUSIVO)
    - "até 2015" => year_max=2015 (INCLUSIVO)
    - "a partir de 2014" => year_min=2014 (INCLUSIVO)
    """
    q = (query or "").strip()
    if not q:
        return q, None, None

    year_min: Optional[int] = None
    year_max: Optional[int] = None

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


def numeric_filter_match(value: Optional[int], operator: str, target: Optional[int]) -> bool:
    """Comparação numérica padronizada para filtros.

    Esse helper existe pra **evitar o bug clássico** do intervalo ficar exclusivo:
    - gte/lte são INCLUSIVOS.
    - gt/lt são EXCLUSIVOS.
    - eq/neq são óbvios.

    Se value ou target forem None, falha (retorna False).
    """
    if value is None or target is None:
        return False

    op = (operator or "").strip().lower()
    if op == "gte":
        return value >= target
    if op == "lte":
        return value <= target
    if op == "gt":
        return value > target
    if op == "lt":
        return value < target
    if op == "eq":
        return value == target
    if op == "neq":
        return value != target

    return False


def year_in_directive_range(year: Optional[int], year_min: Optional[int], year_max: Optional[int]) -> bool:
    """Valida um ano contra as diretivas extraídas.

    **INCLUSIVO nas bordas**:
      - year_min => year >= year_min
      - year_max => year <= year_max
    """
    if year is None:
        return False

    if year_min is not None and not numeric_filter_match(year, "gte", year_min):
        return False
    if year_max is not None and not numeric_filter_match(year, "lte", year_max):
        return False
    return True


def get_user_plan_snapshot(db: Session, user_id) -> Dict[str, Any]:
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

        if hasattr(Subscription, "account_id") and getattr(user, "account_id", None) is not None:
            q = q.filter(Subscription.account_id == user.account_id)
        elif hasattr(Subscription, "user_id"):
            q = q.filter(Subscription.user_id == user_id)
        else:
            return snap

        if hasattr(Subscription, "status"):
            q = q.filter(Subscription.status == "active")
        elif hasattr(Subscription, "is_active"):
            q = q.filter(Subscription.is_active.is_(True))

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
    """Cria wishlist e opcionalmente cria filtros de ano/preço se diretivas existirem."""
    try:
        db.rollback()
    except Exception:
        pass

    max_wishlists = get_max_wishlists_for_user(db, user_id)
    count = db.query(func.count(Wishlist.id)).filter(Wishlist.user_id == user_id).scalar() or 0
    if count >= max_wishlists:
        return False, f"Limite atingido: {max_wishlists} wishlists no seu plano."

    cleaned_query, year_min, year_max = _extract_year_directives(query)
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

    filters = []
    # IMPORTANTE: year range é INCLUSIVO => gte/lte
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

    # build token index for scalable matching
    try:
        rebuild_tokens_for_wishlist(db, w)
        db.commit()
    except Exception:
        db.rollback()

    run_summary = trigger_initial_run_for_wishlist(db, w, run_reason="wishlist_created")

    if run_summary.get("triggered", 0) > 0:
        return True, "Wishlist criada com sucesso e executada agora."
    return True, "Wishlist criada."


def trigger_initial_run_for_wishlist(db: Session, wishlist: Wishlist, *, run_reason: str = "wishlist_created") -> Dict[str, Any]:
    """Dispara a primeira execução de uma wishlist recém-criada no pipeline oficial.

    Estratégia:
    - reaproveita `run_source_for_all_wishlists` (mesmo executor do scheduler)
    - roda apenas fontes permitidas para a wishlist
    - força execução para evitar esperar o ciclo normal (`force=True`)
    - mantém anti-spam pelo dedupe de notifications + atualização de source_state
    """
    if not wishlist:
        return {"triggered": 0, "ok": 0, "skipped": 0, "failed": 0, "sources": []}

    allowed_map = allowed_sources_for_wishlists(db, [wishlist])
    sources = sorted(allowed_map.get(wishlist.id) or [])
    if not sources:
        log(
            db,
            "info",
            "wishlist",
            "initial_run_skipped_no_sources",
            {
                "wishlist_id": str(wishlist.id),
                "run_reason": run_reason,
            },
            event_type="wishlist_initial_run",
            tags=["wishlist", run_reason, "skipped"],
        )
        db.commit()
        return {"triggered": 0, "ok": 0, "skipped": 1, "failed": 0, "sources": []}

    out = {"triggered": len(sources), "ok": 0, "skipped": 0, "failed": 0, "sources": []}
    for src in sources:
        res = run_source_for_all_wishlists(
            db,
            src,
            kind="wishlist_created",
            force=True,
            ignore_backoff=False,
            run_reason=run_reason,
        )
        status = str((res or {}).get("status") or "unknown")
        out["sources"].append({"source": src, "status": status})

        if bool((res or {}).get("ok", False)) and status not in {"error", "blocked"}:
            out["ok"] += 1
        elif status in {"skipped", "not_due"}:
            out["skipped"] += 1
        else:
            out["failed"] += 1

    log(
        db,
        "info",
        "wishlist",
        "initial_run_dispatched",
        {
            "wishlist_id": str(wishlist.id),
            "run_reason": run_reason,
            "triggered": out["triggered"],
            "ok": out["ok"],
            "skipped": out["skipped"],
            "failed": out["failed"],
            "sources": out["sources"],
        },
        event_type="wishlist_initial_run",
        tags=["wishlist", run_reason],
    )
    db.commit()
    return out


def remove_wishlist(db: Session, user_id, index: int):
    wishlists = list_wishlists(db, user_id)
    if index < 1 or index > len(wishlists):
        return False, "Número inválido. Use /wishlist listar."

    w = wishlists[index - 1]
    try:
        _delete_wishlist_explicit(
            db,
            w,
            actor_user_id=user_id,
            caller="wishlists_service.remove_wishlist",
            reason="user_requested_single_delete",
            flow_context="wishlist_remove",
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        return False, "Erro ao remover wishlist: dependências remanescentes inesperadas."
    except SQLAlchemyError:
        db.rollback()
        return False, "Erro ao remover wishlist por falha no banco de dados."
    return True, "Wishlist removida."




def remove_all_wishlists(db: Session, user_id):
    """Remove todas as wishlists do usuário com limpeza explícita de dependências."""
    wishlists = list_wishlists(db, user_id)
    try:
        for w in wishlists:
            _delete_wishlist_explicit(
                db,
                w,
                actor_user_id=user_id,
                caller="wishlists_service.remove_all_wishlists",
                reason="user_requested_bulk_delete",
                flow_context="wishlist_clear",
            )
        db.commit()
    except IntegrityError:
        db.rollback()
        return False, "Erro ao remover wishlists: dependências remanescentes inesperadas."
    except SQLAlchemyError:
        db.rollback()
        return False, "Erro ao remover wishlists por falha no banco de dados."
    return True, f"{len(wishlists)} wishlists removidas."

def add_filter(db: Session, wishlist_id, field: str, operator: str, value: str):
    field = (field or "").strip().lower()
    operator = (operator or "").strip().lower()
    value = (value or "").strip()

    if field not in ("price", "source", "year", "color", "city", "state"):
        return False, "Campo inválido. Use: price | year | source | color | city | state"

    if field in ("price", "year") and operator not in ("lt", "lte", "gt", "gte", "eq", "neq"):
        return False, f"Operador inválido para {field}. Use: lt|lte|gt|gte|eq|neq"

    if field == "source" and operator not in ("eq", "neq"):
        return False, "Operador inválido para source. Use: eq|neq"

    if field in ("color", "city", "state") and operator not in ("eq", "neq"):
        return False, f"Operador inválido para {field}. Use: eq|neq"

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

    if field in ("color", "city"):
        if len(value.strip()) < 2:
            return False, f"Valor inválido para {field}."
        value = value.strip()

    if field == "state":
        uf = value.strip().upper()
        if uf not in KNOWN_STATES:
            return False, "Valor inválido para state. Use UF (ex: SP, RJ, MG)."
        value = uf

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


def _delete_wishlist_explicit(
    db: Session,
    wishlist: Wishlist,
    *,
    actor_user_id,
    caller: str,
    reason: str,
    flow_context: str,
) -> None:
    """Centraliza remoção explícita de wishlist com auditoria obrigatória."""
    payload = {
        "wishlist_id": str(wishlist.id),
        "user_id": str(getattr(wishlist, "user_id", actor_user_id)),
        "actor_user_id": str(actor_user_id),
        "caller": caller,
        "reason": reason,
        "flow_context": flow_context,
    }
    logger.info("wishlist_delete_explicit", extra=payload)
    log(
        db,
        "warn",
        "wishlist",
        "wishlist_delete_explicit",
        payload,
        event_type="wishlist_delete_explicit",
    )

    deleted_filters = db.execute(
        delete(WishlistFilter).where(WishlistFilter.wishlist_id == wishlist.id)
    ).rowcount or 0
    deleted_listing_activity = db.execute(
        delete(WishlistListingActivity).where(WishlistListingActivity.wishlist_id == wishlist.id)
    ).rowcount or 0
    deleted_tokens = db.execute(
        delete(WishlistToken).where(WishlistToken.wishlist_id == wishlist.id)
    ).rowcount or 0

    payload["deleted_counts"] = {
        "wishlist_filters": int(deleted_filters),
        "wishlist_listing_activity": int(deleted_listing_activity),
        "wishlist_tokens": int(deleted_tokens),
    }

    db.delete(wishlist)
