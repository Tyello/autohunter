from __future__ import annotations

import time

from app.db.session import SessionLocal
from app.models.car_listing import CarListing
from app.models.wishlist_tracked_listing import WishlistTrackedListing
from app.services.system_logs_service import log
from app.services.wishlist_tracking_service import evaluate_price_drop_alert, refresh_tracked_listing_snapshot
from app.core.settings import settings


def job_tracking_price_alerts() -> None:
    t0 = time.time()
    with SessionLocal() as db:
        try:
            batch = max(1, int(getattr(settings, "tracking_price_alerts_batch_size", 50) or 50))
            rows = (
                db.query(WishlistTrackedListing, CarListing)
                .outerjoin(CarListing, CarListing.id == WishlistTrackedListing.car_listing_id)
                .filter(WishlistTrackedListing.price_drop_alert_enabled.is_(True))
                .order_by(WishlistTrackedListing.updated_at.asc())
                .limit(batch)
                .all()
            )
            alerted = 0
            for tracked, listing in rows:
                summary = refresh_tracked_listing_snapshot(db, tracked, listing)
                if evaluate_price_drop_alert(db, tracked, summary):
                    alerted += 1
            db.commit()
            log(db, "info", "tracking_alerts", "job ok", {"checked": len(rows), "alerted": alerted, "ms": int((time.time()-t0)*1000)})
            db.commit()
        except Exception as e:
            db.rollback()
            log(db, "error", "tracking_alerts", "job failed", {"error": str(e), "ms": int((time.time()-t0)*1000)})
            db.commit()
