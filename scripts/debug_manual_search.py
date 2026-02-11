from app.db.session import SessionLocal
from app.services.search_service import manual_search

with SessionLocal() as db:
    res = manual_search(
        db,
        query="a6",
        sources=["icarros"],
        limit=5,
        force_scrape=True,
    )
    for r in res:
        print(r.source, r.title, r.price, r.thumbnail_url, r.url, r.updated_at, r.created_at)
