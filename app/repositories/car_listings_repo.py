from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import func, case
from app.models.car_listing import CarListing

import re


_RE_KM_IN_TITLE = re.compile(r"\b(\d{1,3}(?:\.\d{3})*|\d+)\s*km\b", re.I)


def _format_km_ptbr(value: int) -> str:
    # 79000 -> "79.000"
    return f"{value:,}".replace(",", ".")


def _normalize_km(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        if isinstance(value, (int, float)):
            n = int(value)
            return _format_km_ptbr(n) if n > 0 else None
        s = str(value).strip()
        digits = re.sub(r"\D+", "", s)
        if not digits:
            return None
        n = int(digits)
        return _format_km_ptbr(n) if n > 0 else None
    except Exception:
        return None


def _decorate_title_with_year_km(title: str | None, year, km) -> str | None:
    """Persist year/km without schema changes.

    Some scrapers output fields like `year` and `km`, but the DB table doesn't
    have those columns. Instead of failing the bulk insert, we encode them into
    the title in a way that the bot already knows how to extract.
    """
    t = (title or "").strip()
    if not t:
        return title

    # year
    try:
        y = int(year) if year is not None and str(year).strip() else None
    except Exception:
        y = None
    if y and (str(y) not in t):
        t = f"{t} {y}".strip()

    # km
    km_s = _normalize_km(km)
    if km_s and not _RE_KM_IN_TITLE.search(t):
        t = f"{t} {km_s} km".strip()

    return t or None

def insert_ignore_duplicates_return_ids(db: Session, listings: list[dict]):
    """
    Faz bulk upsert por (source, external_id).

    Motivo: em scraping é comum o primeiro ingest vir incompleto (sem title/thumbnail),
    e um ingest posterior completar os campos. Se fizermos DO NOTHING, o registro
    fica para sempre "capado" e o bot cai no fallback de enviar só texto.

    Regra de update:
      - só preenche campos que ainda estão NULL (COALESCE(existing, excluded))
      - mantém o que já existe, para não sobrescrever dado bom com dado ruim.
    """
    listings = _dedupe_listings(listings)
    if not listings:
        return []

    # Drop/encode extra fields (ex: year/km) to avoid SQLAlchemy CompileError
    # "Unconsumed column names" on bulk insert.
    allowed_cols = set(CarListing.__table__.columns.keys())
    prepared: list[dict] = []
    for l in listings:
        if not isinstance(l, dict):
            continue
        year = l.pop("year", None)
        km = l.pop("km", None)
        if l.get("title"):
            l["title"] = _decorate_title_with_year_km(l.get("title"), year, km)
        # keep only columns that actually exist in the table
        prepared.append({k: v for k, v in l.items() if k in allowed_cols})

    listings = prepared
    if not listings:
        return []

    stmt = insert(CarListing).values(listings)

    stmt = stmt.on_conflict_do_update(
        index_elements=["source", "external_id"],
        set_={
            # Regra: manter o que já existe quando é bom; completar/atualizar quando o existente é "ruim".
            #
            # Isso resolve casos reais onde o primeiro ingest vem genérico ("comprar ...") / sem foto,
            # e um scrape posterior (detail/enrich) consegue preencher com dados bons.
            "title": case(
                (
                    (
                        CarListing.title.is_(None)
                        | (func.length(CarListing.title) < 6)
                        | CarListing.title.ilike("%comparar%")
                        | CarListing.title.ilike("reservado%")
                        | CarListing.title.ilike("%| a%")
                        | CarListing.title.ilike("comprar%")
                        | CarListing.title.ilike("foto %")
                    )
                    & stmt.excluded.title.isnot(None)
                    & (func.length(stmt.excluded.title) >= 6)
                    & ~stmt.excluded.title.ilike("comprar%")
                    & ~stmt.excluded.title.ilike("%comparar%")
                    & ~stmt.excluded.title.ilike("reservado%")
                    & ~stmt.excluded.title.ilike("%| a%")
                    ,
                    stmt.excluded.title,
                ),
                else_=CarListing.title,
            ),
            "thumbnail_url": case(
                (
                    stmt.excluded.thumbnail_url.isnot(None)
                    & (
                        CarListing.thumbnail_url.is_(None)
                        | CarListing.thumbnail_url.ilike("%logo_icarros_compartilhar%")
                        | CarListing.thumbnail_url.ilike("%/comum/imagens/logo_%")
                        | CarListing.thumbnail_url.ilike("%/comum/imagens/%logo%")
                        | CarListing.thumbnail_url.ilike("%fit-in/320%")
                        | CarListing.thumbnail_url.ilike("%fit-in/400%")
                        | CarListing.thumbnail_url.ilike("%fit-in/480%")
                        | CarListing.thumbnail_url.ilike("%w=320%")
                        | CarListing.thumbnail_url.ilike("%width=320%")
                        | CarListing.title.is_(None)
                        | CarListing.title.ilike("comprar%")
                        | CarListing.title.ilike("%comparar%")
                    ),
                    stmt.excluded.thumbnail_url,
                ),
                else_=CarListing.thumbnail_url,
            ),
            "price": case(
                (
                    stmt.excluded.price.isnot(None)
                    & (
                        CarListing.price.is_(None)
                        | (CarListing.price <= 0)
                        | CarListing.title.is_(None)
                        | CarListing.title.ilike("comprar%")
                        | CarListing.title.ilike("%comparar%")
                    ),
                    stmt.excluded.price,
                ),
                else_=CarListing.price,
            ),
            "location": case(
                (
                    stmt.excluded.location.isnot(None)
                    & (
                        CarListing.location.is_(None)
                        | CarListing.title.is_(None)
                        | CarListing.title.ilike("comprar%")
                        | CarListing.title.ilike("%comparar%")
                    ),
                    stmt.excluded.location,
                ),
                else_=CarListing.location,
            ),
            # url normalmente é estável; se mudar (ex: resolve redirect #rfae), preferimos o novo
            "url": stmt.excluded.url,
            # marca como "atualizado" quando rodamos um scrape novo (ajuda o /buscar retornar o registro enriquecido)
            "updated_at": func.now(),
        },
    )


    stmt = stmt.returning(CarListing.id)
    result = db.execute(stmt)
    return [row[0] for row in result.fetchall()]

def _merge_best(a: dict, b: dict) -> dict:
    # Mantém o que já é bom e completa o que está faltando
    out = dict(a)
    for k, v in b.items():
        if out.get(k) is None and v is not None:
            out[k] = v
    # url normalmente é sempre válida; se vier diferente, mantém a mais "nova"
    if b.get("url"):
        out["url"] = b["url"]
    return out

def _dedupe_listings(listings: list[dict]) -> list[dict]:
    by_key: dict[tuple[str, str], dict] = {}
    for l in listings:
        key = (l.get("source"), l.get("external_id"))
        if not key[0] or not key[1]:
            continue
        if key in by_key:
            by_key[key] = _merge_best(by_key[key], l)
        else:
            by_key[key] = l
    return list(by_key.values())
