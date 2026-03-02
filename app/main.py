from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, WebSocket
from sqlalchemy import text
from typing import List
from sqlalchemy.orm import Session

from app.core.settings import settings

from app.scheduler.run import start_scheduler

from app.models.car_listing import CarListing
from app.schemas.car_listing import CarListingOut
from app.scrapers.olx import get_olx_health_snapshot

from app.db.deps import get_db
from app.web.routes_auth_facebook import router as facebook_auth_router
from app.web.routes_fb_agent import router as facebook_agent_router
from app.integrations.facebook.agent_ws import handle_fb_agent_ws

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan handler (substitui startup/shutdown).
    Evita warnings do @app.on_event e centraliza o ciclo de vida.
    """
    if settings.enable_scheduler_in_api:
        app.state.scheduler = start_scheduler()
    try:
        yield
    finally:
        scheduler = getattr(app.state, "scheduler", None)
        if scheduler:
            scheduler.shutdown(wait=False)


app = FastAPI(title="AutoHunter", version="0.1.0", lifespan=lifespan)
app.include_router(facebook_auth_router)
app.include_router(facebook_agent_router)


@app.websocket("/ws/fb/agent")
async def fb_agent_ws(websocket: WebSocket):
    await handle_fb_agent_ws(websocket)

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