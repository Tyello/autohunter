from datetime import datetime, timezone
import re
import uuid

from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import func, case, literal_column, literal, text
from sqlalchemy.exc import ProgrammingError, OperationalError

from app.models.car_listing import CarListing
from app.services.cross_source_dedupe_service import compute_cross_source_fingerprint


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


def _prefer_title(existing: str | None, incoming: str | None, source: str | None) -> str | None:
    if incoming is None:
        return existing
    source = (source or "").lower()
    if source == "gogarage":
        return incoming
    if source == "turboclass":
        if existing is None or len(incoming) > (len(existing) + 3):
            return incoming
        return existing

    existing_l = (existing or "").lower()
    looks_bad = (
        existing is None
        or len(existing) < 6
        or existing_l.startswith("link para")
        or " visto" in existing_l
        or " pts" in existing_l
        or " pontos" in existing_l
        or "comparar" in existing_l
        or existing_l.startswith("reservado")
        or "| a" in existing_l
        or existing_l.startswith("comprar")
    )
    return incoming if looks_bad else existing


def _prefer_thumbnail(existing: str | None, incoming: str | None) -> str | None:
    if existing is None and incoming is not None:
        return incoming
    if incoming is None:
        return existing

    existing_l = (existing or "").lower()
    incoming_l = incoming.lower()
    looks_bad = (
        "logo_icarros_compartilhar" in existing_l
        or "/comum/imagens/logo" in existing_l
        or "thumb" in existing_l
        or "fit-in/320" in existing_l
        or "fit-in/480" in existing_l
    )
    if looks_bad and "logo_icarros_compartilhar" not in incoming_l:
        return incoming
    return existing


def _is_missing_on_conflict_constraint(exc) -> bool:
    msg = str(getattr(exc, "orig", exc)).lower()
    # Postgres: "there is no unique or exclusion constraint matching the on conflict specification"
    # SQLite: "ON CONFLICT clause does not match any PRIMARY KEY or UNIQUE constraint" or "no such table"
    return (
        "there is no unique or exclusion constraint matching the on conflict specification" in msg
        or "on conflict clause does not match any primary key or unique constraint" in msg
    )


def _homogenize_bulk_insert_rows(rows: list[dict]) -> list[dict]:
    if not rows:
        return []

    bulk_keys: set[str] = set().union(*(row.keys() for row in rows))
    return [{k: row.get(k) for k in bulk_keys} for row in rows]


def _fallback_upsert_without_constraint(db: Session, listings: list[dict], *, with_stats: bool):
    now = datetime.now(timezone.utc)
    ids: list[uuid.UUID] = []
    inserted_new = 0
    updated = 0

    for listing in listings:
        source = listing.get("source")
        external_id = listing.get("external_id")
        if not source or not external_id:
            continue

        row = (
            db.query(CarListing)
            .filter(CarListing.source == source, CarListing.external_id == external_id)
            .order_by(CarListing.created_at.asc())
            .first()
        )

        if row is None:
            row = CarListing(
                id=uuid.uuid4(),
                source=source,
                external_id=external_id,
                title=listing.get("title"),
                url=listing.get("url"),
                thumbnail_url=listing.get("thumbnail_url"),
                price=listing.get("price"),
                currency=listing.get("currency") or "BRL",
                location=listing.get("location"),
                extras=listing.get("extras") or {},
                raw_payload=listing.get("raw_payload"),
                listing_type=listing.get("listing_type") or "marketplace",
                extractor_version=listing.get("extractor_version"),
                year=listing.get("year"),
                mileage_km=listing.get("mileage_km"),
                fuel_type=listing.get("fuel_type"),
                transmission=listing.get("transmission"),
                make=listing.get("make"),
                model=listing.get("model"),
                version=listing.get("version"),
                seller_type=listing.get("seller_type"),
                city=listing.get("city"),
                state=listing.get("state"),
                color=listing.get("color"),
                doors=listing.get("doors"),
                body_type=listing.get("body_type"),
                cross_source_fingerprint=listing.get("cross_source_fingerprint"),
                is_sold=bool(listing.get("is_sold")),
                sold_at=listing.get("sold_at"),
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            db.flush()
            inserted_new += 1
        else:
            # Track if any field changed
            changed = False

            # title: apply same logic as ON CONFLICT
            new_title = _prefer_title(row.title, listing.get("title"), row.source)
            if new_title != row.title:
                changed = True
            row.title = new_title

            # url: always prefer new
            new_url = listing.get("url") or row.url
            if new_url != row.url:
                changed = True
            row.url = new_url

            # thumbnail_url
            new_thumbnail = _prefer_thumbnail(row.thumbnail_url, listing.get("thumbnail_url"))
            if new_thumbnail != row.thumbnail_url:
                changed = True
            row.thumbnail_url = new_thumbnail

            # price: coalesce(existing, new)
            new_price = row.price if row.price is not None else listing.get("price")
            if new_price != row.price:
                changed = True
            row.price = new_price

            # location: coalesce(existing, new)
            new_location = row.location if row.location is not None else listing.get("location")
            if new_location != row.location:
                changed = True
            row.location = new_location

            # year: coalesce(existing, new)
            new_year = row.year if row.year is not None else listing.get("year")
            if new_year != row.year:
                changed = True
            row.year = new_year

            # make: coalesce(existing, new)
            new_make = row.make if row.make is not None else listing.get("make")
            if new_make != row.make:
                changed = True
            row.make = new_make

            # model: coalesce(existing, new)
            new_model = row.model if row.model is not None else listing.get("model")
            if new_model != row.model:
                changed = True
            row.model = new_model

            # mileage_km: coalesce(existing, new)
            new_mileage_km = row.mileage_km if row.mileage_km is not None else listing.get("mileage_km")
            if new_mileage_km != row.mileage_km:
                changed = True
            row.mileage_km = new_mileage_km

            # fuel_type: coalesce(existing, new)
            new_fuel_type = row.fuel_type if row.fuel_type is not None else listing.get("fuel_type")
            if new_fuel_type != row.fuel_type:
                changed = True
            row.fuel_type = new_fuel_type

            # transmission: coalesce(existing, new)
            new_transmission = row.transmission if row.transmission is not None else listing.get("transmission")
            if new_transmission != row.transmission:
                changed = True
            row.transmission = new_transmission

            # version: coalesce(existing, new)
            new_version = row.version if row.version is not None else listing.get("version")
            if new_version != row.version:
                changed = True
            row.version = new_version

            # seller_type: coalesce(existing, new)
            new_seller_type = row.seller_type if row.seller_type is not None else listing.get("seller_type")
            if new_seller_type != row.seller_type:
                changed = True
            row.seller_type = new_seller_type

            # city: coalesce(existing, new)
            new_city = row.city if row.city is not None else listing.get("city")
            if new_city != row.city:
                changed = True
            row.city = new_city

            # state: coalesce(existing, new)
            new_state = row.state if row.state is not None else listing.get("state")
            if new_state != row.state:
                changed = True
            row.state = new_state

            # color: coalesce(existing, new)
            new_color = row.color if row.color is not None else listing.get("color")
            if new_color != row.color:
                changed = True
            row.color = new_color

            # doors: coalesce(existing, new)
            new_doors = row.doors if row.doors is not None else listing.get("doors")
            if new_doors != row.doors:
                changed = True
            row.doors = new_doors

            # body_type: coalesce(existing, new)
            new_body_type = row.body_type if row.body_type is not None else listing.get("body_type")
            if new_body_type != row.body_type:
                changed = True
            row.body_type = new_body_type

            # cross_source_fingerprint: only update if new value is not None
            if listing.get("cross_source_fingerprint") is not None:
                new_csf = listing.get("cross_source_fingerprint")
                if new_csf != row.cross_source_fingerprint:
                    changed = True
                row.cross_source_fingerprint = new_csf

            # raw_payload: coalesce(existing, new)
            new_raw_payload = row.raw_payload if row.raw_payload is not None else listing.get("raw_payload")
            if new_raw_payload != row.raw_payload:
                changed = True
            row.raw_payload = new_raw_payload

            # extractor_version: coalesce(existing, new)
            new_extractor_version = row.extractor_version if row.extractor_version is not None else listing.get("extractor_version")
            if new_extractor_version != row.extractor_version:
                changed = True
            row.extractor_version = new_extractor_version

            # is_sold: OR semantics
            new_is_sold = bool(row.is_sold) or bool(listing.get("is_sold"))
            if new_is_sold != row.is_sold:
                changed = True
            row.is_sold = new_is_sold

            # sold_at: only update if new value is not None and current is None
            if row.sold_at is None and listing.get("sold_at") is not None:
                new_sold_at = listing.get("sold_at")
                if new_sold_at != row.sold_at:
                    changed = True
                row.sold_at = new_sold_at

            # Liveness: always reset status to 'ativo' and update last_seen_at on upsert
            if row.status != 'ativo':
                changed = True
            row.status = 'ativo'
            row.last_seen_at = now

            # updated_at: only update if any field changed
            if changed:
                row.updated_at = now

            updated += 1

        ids.append(row.id)

    # Commit changes to make them visible to subsequent queries
    db.commit()

    if not with_stats:
        return ids

    return {
        "ids": ids,
        "inserted_new": inserted_new,
        "updated": updated,
        "upserted": len(ids),
    }


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
        prepared_listing = _normalize_controlled_fields(prepared_listing)
        computed_fp = compute_cross_source_fingerprint(prepared_listing)
        if computed_fp is not None:
            prepared_listing["cross_source_fingerprint"] = computed_fp
        prepared.append(prepared_listing)

    listings = _homogenize_bulk_insert_rows(prepared)
    if not listings:
        return []

    stmt = insert(CarListing).values(listings)

    # Bound Python timestamp (not func.now()) so upsert timing has microsecond
    # precision consistently across dialects: SQLite's func.now() compiles to
    # CURRENT_TIMESTAMP, which only has whole-second resolution and can make
    # rapid consecutive upserts (e.g. in tests) appear to not advance in time.
    now_ts = datetime.now(timezone.utc)

    # Extract column value expressions for reuse in both set_ dict and changed detection
    title_expr = case(
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
    )

    thumbnail_url_expr = case(
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
    )

    price_expr = func.coalesce(CarListing.price, stmt.excluded.price)
    location_expr = func.coalesce(CarListing.location, stmt.excluded.location)
    year_expr = func.coalesce(CarListing.year, stmt.excluded.year)
    make_expr = func.coalesce(CarListing.make, stmt.excluded.make)
    model_expr = func.coalesce(CarListing.model, stmt.excluded.model)
    mileage_km_expr = func.coalesce(CarListing.mileage_km, stmt.excluded.mileage_km)
    fuel_type_expr = func.coalesce(CarListing.fuel_type, stmt.excluded.fuel_type)
    transmission_expr = func.coalesce(CarListing.transmission, stmt.excluded.transmission)
    version_expr = func.coalesce(CarListing.version, stmt.excluded.version)
    seller_type_expr = func.coalesce(CarListing.seller_type, stmt.excluded.seller_type)
    city_expr = func.coalesce(CarListing.city, stmt.excluded.city)
    state_expr = func.coalesce(CarListing.state, stmt.excluded.state)
    color_expr = func.coalesce(CarListing.color, stmt.excluded.color)
    doors_expr = func.coalesce(CarListing.doors, stmt.excluded.doors)
    body_type_expr = func.coalesce(CarListing.body_type, stmt.excluded.body_type)
    cross_source_fingerprint_expr = func.coalesce(stmt.excluded.cross_source_fingerprint, CarListing.cross_source_fingerprint)
    raw_payload_expr = func.coalesce(CarListing.raw_payload, stmt.excluded.raw_payload)
    extractor_version_expr = func.coalesce(CarListing.extractor_version, stmt.excluded.extractor_version)

    is_sold_expr = (
        func.coalesce(CarListing.is_sold, False)
        | func.coalesce(stmt.excluded.is_sold, False)
    )

    sold_at_expr = case(
        (
            (CarListing.sold_at.is_(None) & stmt.excluded.sold_at.isnot(None)),
            stmt.excluded.sold_at,
        ),
        else_=CarListing.sold_at,
    )

    url_expr = stmt.excluded.url

    # Build changed detection: OR of is_distinct_from comparisons for all columns except updated_at
    changed = (
        title_expr.is_distinct_from(CarListing.title)
        | thumbnail_url_expr.is_distinct_from(CarListing.thumbnail_url)
        | price_expr.is_distinct_from(CarListing.price)
        | location_expr.is_distinct_from(CarListing.location)
        | year_expr.is_distinct_from(CarListing.year)
        | make_expr.is_distinct_from(CarListing.make)
        | model_expr.is_distinct_from(CarListing.model)
        | mileage_km_expr.is_distinct_from(CarListing.mileage_km)
        | fuel_type_expr.is_distinct_from(CarListing.fuel_type)
        | transmission_expr.is_distinct_from(CarListing.transmission)
        | version_expr.is_distinct_from(CarListing.version)
        | seller_type_expr.is_distinct_from(CarListing.seller_type)
        | city_expr.is_distinct_from(CarListing.city)
        | state_expr.is_distinct_from(CarListing.state)
        | color_expr.is_distinct_from(CarListing.color)
        | doors_expr.is_distinct_from(CarListing.doors)
        | body_type_expr.is_distinct_from(CarListing.body_type)
        | cross_source_fingerprint_expr.is_distinct_from(CarListing.cross_source_fingerprint)
        | raw_payload_expr.is_distinct_from(CarListing.raw_payload)
        | extractor_version_expr.is_distinct_from(CarListing.extractor_version)
        | is_sold_expr.is_distinct_from(CarListing.is_sold)
        | sold_at_expr.is_distinct_from(CarListing.sold_at)
        | url_expr.is_distinct_from(CarListing.url)
    )

    stmt = stmt.on_conflict_do_update(
        index_elements=["source", "external_id"],
        set_={
            # mantém valores já existentes quando não-null; caso contrário, preenche do novo scrape
            "title": title_expr,
            "thumbnail_url": thumbnail_url_expr,
            "price": price_expr,
            "location": location_expr,
            # Promoted common fields: fill when missing.
            "year": year_expr,
            "make": make_expr,
            "model": model_expr,
            "mileage_km": mileage_km_expr,
            "fuel_type": fuel_type_expr,
            "transmission": transmission_expr,
            "version": version_expr,
            "seller_type": seller_type_expr,
            "city": city_expr,
            "state": state_expr,
            "color": color_expr,
            "doors": doors_expr,
            "body_type": body_type_expr,
            "cross_source_fingerprint": cross_source_fingerprint_expr,
            "raw_payload": raw_payload_expr,
            "extractor_version": extractor_version_expr,
            # Sold state: once sold, never revert (OR semantics).
            "is_sold": is_sold_expr,
            # When marking sold, keep the first sold_at we saw (or set it from excluded).
            "sold_at": sold_at_expr,
            # url normalmente é estável; se mudar, preferimos o novo
            "url": url_expr,
            # Liveness: reset status to ativo on every upsert, update last_seen_at
            "status": literal('ativo'),
            "last_seen_at": now_ts,
            # updated_at: only update if any column value changed
            "updated_at": case((changed, literal(now_ts)), else_=CarListing.updated_at),
        },
    )

    # `xmax` is a PostgreSQL system column (not part of mapped table columns),
    # so reference it as a literal SQL column in RETURNING.
    # For SQLite, use a different approach since it doesn't support xmax.
    dialect_name = db.bind.dialect.name.lower()
    if dialect_name == 'sqlite':
        # SQLite: just return IDs; stats tracking is best-effort
        stmt = stmt.returning(CarListing.id)
    else:
        # PostgreSQL and other databases: use xmax to detect inserts
        inserted_expr = (literal_column("xmax") == 0).label("inserted")
        stmt = stmt.returning(CarListing.id, inserted_expr)

    try:
        result = db.execute(stmt)
    except (ProgrammingError, OperationalError) as exc:
        if not _is_missing_on_conflict_constraint(exc):
            raise
        db.rollback()
        return _fallback_upsert_without_constraint(db, listings, with_stats=with_stats)
    rows = result.fetchall()
    ids = [row[0] for row in rows]

    # Commit to make changes visible, and expire the identity map so any
    # already-loaded ORM objects for these rows are re-read fresh on next
    # access (db.execute() bypasses the ORM's in-memory attribute sync).
    db.commit()

    if not with_stats:
        return ids

    # For SQLite, we don't have xmax, so we return zeroed stats
    if dialect_name == 'sqlite':
        return {
            "ids": ids,
            "inserted_new": 0,
            "updated": 0,
            "upserted": len(ids),
        }

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
