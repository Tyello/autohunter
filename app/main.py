from fastapi import FastAPI, Depends
from sqlalchemy import text
from typing import List
from sqlalchemy.orm import Session

from app.core.settings import settings

from app.scheduler.run import start_scheduler

from app.models.car_listing import CarListing
from app.schemas.car_listing import CarListingOut
from app.scrapers.olx import get_olx_health_snapshot

from app.db.deps import get_db

app = FastAPI(title="AutoHunter", version="0.1.0")

_scheduler = None

@app.on_event("startup")
def startup():
    global _scheduler
    if settings.enable_scheduler_in_api:
        _scheduler = start_scheduler()

@app.on_event("shutdown")
def shutdown():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/db-check")
def db_check(db: Session = Depends(get_db)):
    db.execute(text("select 1"))
    return {"database": "connected"}

@app.get("/listings", response_model=List[CarListingOut])
def list_listings(
    source: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    query = db.query(CarListing)

    if source:
        query = query.filter(CarListing.source == source)

    listings = query.order_by(CarListing.created_at.desc()).limit(limit).all()
    return listings

@app.get("/admin/health")
def admin_health():
    return {
        "status": "ok",
        "olx": get_olx_health_snapshot(),
    }