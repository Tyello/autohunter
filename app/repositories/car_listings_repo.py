from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import func, case, literal_column
from app.models.car_listing import CarListing

import re


_RE_KM_IN_TITLE = re.compile(r"\b(\d{1,3}(?:\.\d{3})*|\d+)\s*km\b", re.I)

_FUEL_ALLOWED = {"gasoline", "ethanol", "flex", "diesel", "electric", "hybrid"}
_TRANSMISSION_ALLOWED = {"manual", "automatic", "cvt", "automated", "semi_automatic"}
_SELLER_ALLOWED = {"dealer", "private", "unknown"}
_LISTING_TYPE_ALLOWED = {"marketplace", "auction_lot", "classified"}


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

def _norm_token(value) -> str | None:
    if value is None:
        return None
    s = str(value).strip().lower()
    return s or None


def _normalize_controlled_fields(listing: dict) -> dict:
    out = dict(listing)

    fuel = _norm_token(out.get("fuel_type"))
    out["fuel_type"] = fuel if fuel in _FUEL_ALLOWED else None

    transmission = _norm_token(out.get("transmission"))
    out["transmission"] = transmission if transmission in _TRANSMISSION_ALLOWED else None

    seller = _norm_token(out.get("seller_type"))
    if seller not in _SELLER_ALLOWED:
        seller = "unknown" if seller else None
    out["seller_type"] = seller

    listing_type = _norm_token(out.get("listing_type"))
    out["listing_type"] = listing_type if listing_type in _LISTING_TYPE_ALLOWED else "marketplace"

    return out


def insert_ignore_duplicates_return_ids(db: Session, listings: list[dict], with_stats: bool = False):
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
    #
    # IMPORTANT:
    # - If the schema already has `year`/`km` columns, keep them.
    # - If it doesn't, encode them into title (legacy behavior).
    allowed_cols = set(CarListing.__table__.columns.keys())
    has_year_col = "year" in allowed_cols
    # legacy scrapers might send "km"; schema uses mileage_km
    has_km_col = ("km" in allowed_cols) or ("mileage_km" in allowed_cols)
    prepared: list[dict] = []
    for l in listings:
        if not isinstance(l, dict):
            continue

        year = None
        km = None
        if not has_year_col:
            year = l.pop("year", None)
        # mileage: accept both keys
        km_in = None
        if "mileage_km" in l and l.get("mileage_km") is not None:
            km_in = l.pop("mileage_km", None)
        if "km" in l and l.get("km") is not None:
            km_in = l.pop("km", None)

        if "mileage_km" in allowed_cols and km_in is not None:
            l["mileage_km"] = km_in
        elif "km" in allowed_cols and km_in is not None:
            l["km"] = km_in
        else:
            km = km_in

        # Only decorate when we had to pop (legacy schema without columns).
        if l.get("title") and (year is not None or km is not None):
            l["title"] = _decorate_title_with_year_km(l.get("title"), year, km)
        # keep only columns that actually exist in the table
        prepared_listing = {k: v for k, v in l.items() if k in allowed_cols}
        prepared.append(_normalize_controlled_fields(prepared_listing))

    listings = prepared
    if not listings:
        return []

    stmt = insert(CarListing).values(listings)

    stmt = stmt.on_conflict_do_update(
        index_elements=["source", "external_id"],
        set_={
            # mantém valores já existentes quando não-null; caso contrário, preenche do novo scrape
            "title": case(
    (
        # GoGarage: external_id = slug, então é seguro sempre atualizar para o título mais recente.
        (CarListing.source == "gogarage") & stmt.excluded.title.isnot(None),
        stmt.excluded.title,
    ),
    (
        # TurboClass: o primeiro ingest pode vir "capado" (sem 'SI', sem ano/modelo etc).
        # Se o novo título for claramente mais informativo, atualiza.
        (CarListing.source == "turboclass")
        & stmt.excluded.title.isnot(None)
        & (
            CarListing.title.is_(None)
            | (func.length(stmt.excluded.title) > (func.length(CarListing.title) + 3))
        ),
        stmt.excluded.title,
    ),
    (
        # atualiza título quando o existente é claramente "ruim" (ruído de UI / concat quebrada)
        (
            CarListing.title.is_(None)
            | (func.length(CarListing.title) < 6)
            | CarListing.title.ilike('link para%')
            | CarListing.title.ilike('% visto%')
            | CarListing.title.ilike('% pts%')
            | CarListing.title.ilike('% pontos%')
            | CarListing.title.ilike('%comparar%')
            | CarListing.title.ilike('reservado%')
            | CarListing.title.ilike('%| a%')
            | CarListing.title.ilike('comprar%')
        )
        & stmt.excluded.title.isnot(None),
        stmt.excluded.title,
    ),
    else_=CarListing.title,
),
            "thumbnail_url": case(
    (
        # Preenche quando não existe
        (CarListing.thumbnail_url.is_(None) & stmt.excluded.thumbnail_url.isnot(None)),
        stmt.excluded.thumbnail_url,
    ),
    (
        # Troca quando o existente é claramente ruim (logo/placeholder/thumb pequeno)
        (
            CarListing.thumbnail_url.ilike('%logo_icarros_compartilhar%')
            | CarListing.thumbnail_url.ilike('%/comum/imagens/logo%')
            | CarListing.thumbnail_url.ilike('%thumb%')
            | CarListing.thumbnail_url.ilike('%fit-in/320%')
            | CarListing.thumbnail_url.ilike('%fit-in/480%')
        )
        & stmt.excluded.thumbnail_url.isnot(None)
        & (~stmt.excluded.thumbnail_url.ilike('%logo_icarros_compartilhar%')),
        stmt.excluded.thumbnail_url,
    ),
    else_=CarListing.thumbnail_url,
),
            "price": func.coalesce(CarListing.price, stmt.excluded.price),
            "location": func.coalesce(CarListing.location, stmt.excluded.location),
            # Promoted common fields: fill when missing.
            "year": func.coalesce(CarListing.year, stmt.excluded.year),
            "make": func.coalesce(CarListing.make, stmt.excluded.make),
            "model": func.coalesce(CarListing.model, stmt.excluded.model),
            "mileage_km": func.coalesce(CarListing.mileage_km, stmt.excluded.mileage_km),
            "fuel_type": func.coalesce(CarListing.fuel_type, stmt.excluded.fuel_type),
            "transmission": func.coalesce(CarListing.transmission, stmt.excluded.transmission),
            "version": func.coalesce(CarListing.version, stmt.excluded.version),
            "seller_type": func.coalesce(CarListing.seller_type, stmt.excluded.seller_type),
            "city": func.coalesce(CarListing.city, stmt.excluded.city),
            "state": func.coalesce(CarListing.state, stmt.excluded.state),
            "color": func.coalesce(CarListing.color, stmt.excluded.color),
            "raw_payload": func.coalesce(CarListing.raw_payload, stmt.excluded.raw_payload),
            "extractor_version": func.coalesce(CarListing.extractor_version, stmt.excluded.extractor_version),
            # Sold state: once sold, never revert (OR semantics).
            "is_sold": (
                func.coalesce(CarListing.is_sold, False)
                | func.coalesce(stmt.excluded.is_sold, False)
            ),
            # When marking sold, keep the first sold_at we saw (or set it from excluded).
            "sold_at": case(
                (
                    (CarListing.sold_at.is_(None) & stmt.excluded.sold_at.isnot(None)),
                    stmt.excluded.sold_at,
                ),
                else_=CarListing.sold_at,
            ),
            # url normalmente é estável; se mudar, preferimos o novo
            "updated_at": func.now(),
            "url": stmt.excluded.url,
        },
    )

    # `xmax` is a PostgreSQL system column (not part of mapped table columns),
    # so reference it as a literal SQL column in RETURNING.
    inserted_expr = (literal_column("xmax") == 0).label("inserted")
    stmt = stmt.returning(CarListing.id, inserted_expr)
    result = db.execute(stmt)
    rows = result.fetchall()
    ids = [row[0] for row in rows]

    if not with_stats:
        return ids

    inserted_new = sum(1 for row in rows if bool(row[1]))
    upserted = len(rows)
    updated = upserted - inserted_new
    return {
        "ids": ids,
        "inserted_new": inserted_new,
        "updated": updated,
        "upserted": upserted,
    }

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
