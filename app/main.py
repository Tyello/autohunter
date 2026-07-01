from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, Query, WebSocket
from sqlalchemy import text
from typing import List
from sqlalchemy.orm import Session

from app.core.settings import settings

from app.scheduler.run import start_scheduler

from app.models.car_listing import CarListing
from app.schemas.car_listing import CarListingOut
from app.scrapers.olx import get_olx_health_snapshot
from app.services.scrape_jobs_service import has_active_source_queue_partial_index
from app.services.db_runtime_safety_service import check_database_runtime_role

from app.db.deps import get_db
from app.web.routes_auth_facebook import router as facebook_auth_router
from app.web.routes_fb_agent import router as facebook_agent_router
from app.web.routes_mercadopago_webhook import router as mercadopago_webhook_router
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
app.include_router(mercadopago_webhook_router)


@app.websocket("/ws/fb/agent")
async def fb_agent_ws(websocket: WebSocket):
    await handle_fb_agent_ws(websocket)

@app.get("/health")
def health(db: Session = Depends(get_db)):
    has_index = has_active_source_queue_partial_index(db)
    db_role = check_database_runtime_role(db)
    return {
        "status": "ok" if has_index and db_role.ok else "warning",
        "scrape_jobs_conflict_index_ok": has_index,
        "database_runtime_role": {
            "status": db_role.status,
            "role": db_role.role,
            "source": db_role.source,
            "warning": db_role.warning,
        },
    }

@app.get("/db-check")
def db_check(db: Session = Depends(get_db)):
    db.execute(text("select 1"))
    return {"database": "connected"}

@app.get("/listings", response_model=List[CarListingOut])
def list_listings(
    source: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    query = db.query(CarListing)

    if source:
        query = query.filter(CarListing.source == source)

    listings = query.order_by(CarListing.created_at.desc()).limit(limit).all()
    return listings

@app.get("/admin/health")
def admin_health(db: Session = Depends(get_db)):
    has_index = has_active_source_queue_partial_index(db)
    db_role = check_database_runtime_role(db)
    return {
        "status": "ok" if has_index and db_role.ok else "warning",
        "scrape_jobs_conflict_index_ok": has_index,
        "database_runtime_role": {
            "status": db_role.status,
            "role": db_role.role,
            "source": db_role.source,
            "warning": db_role.warning,
        },
        "olx": get_olx_health_snapshot(),
    }
