from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import func
from app.models.car_listing import CarListing

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

    stmt = insert(CarListing).values(listings)

    stmt = stmt.on_conflict_do_update(
        index_elements=["source", "external_id"],
        set_={
            # mantém valores já existentes quando não-null; caso contrário, preenche do novo scrape
            "title": func.coalesce(CarListing.title, stmt.excluded.title),
            "thumbnail_url": func.coalesce(CarListing.thumbnail_url, stmt.excluded.thumbnail_url),
            "price": func.coalesce(CarListing.price, stmt.excluded.price),
            "location": func.coalesce(CarListing.location, stmt.excluded.location),
            # url normalmente é estável; se mudar, preferimos o novo
            "url": stmt.excluded.url,
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
