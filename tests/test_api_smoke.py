from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.models.car_listing import CarListing


def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_db_check_ok(client):
    resp = client.get("/db-check")
    assert resp.status_code == 200
    assert resp.json() == {"database": "connected"}


def test_listings_order_filter_and_limit(client, db):
    now = datetime.now(timezone.utc)

    l_old = CarListing(
        source="olx",
        external_id="OLX1",
        title="Honda Civic SI 1994",
        url="https://www.olx.com.br/1",
        price=Decimal("32000"),
        currency="BRL",
        created_at=now - timedelta(hours=2),
        updated_at=now - timedelta(hours=2),
    )
    l_new = CarListing(
        source="mercadolivre",
        external_id="MLB6160123242",
        title="Honda Civic Hatch SI 1994",
        url="https://carro.mercadolivre.com.br/MLB-6160123242-_JM",
        price=Decimal("85900"),
        currency="BRL",
        created_at=now - timedelta(minutes=5),
        updated_at=now - timedelta(minutes=5),
    )

    db.add_all([l_old, l_new])
    db.commit()

    # Default: newest first
    resp = client.get("/listings")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["source"] == "mercadolivre"
    assert data[1]["source"] == "olx"

    # Filter by source
    resp = client.get("/listings", params={"source": "olx"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["source"] == "olx"

    # Limit
    resp = client.get("/listings", params={"limit": 1})
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_admin_health_includes_olx_snapshot(client):
    resp = client.get("/admin/health")
    assert resp.status_code == 200
    payload = resp.json()

    assert payload["status"] == "ok"
    assert "olx" in payload
    # keep it robust: just validate some stable keys
    assert "browser_fallback_24h" in payload["olx"]
    assert "force_browser_config_enabled" in payload["olx"]


def test_listings_limit_validation(client):
    resp = client.get("/listings", params={"limit": 0})
    assert resp.status_code == 422

    resp = client.get("/listings", params={"limit": 500})
    assert resp.status_code == 422
