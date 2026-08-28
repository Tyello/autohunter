import time
from datetime import datetime, timezone
from app.repositories import car_listings_repo


def test_updated_at_unchanged_when_all_fields_identical(db):
    """
    Upsert do mesmo listing com todos os campos idênticos → updated_at não muda.
    """
    # First insert
    payload1 = [
        {
            "source": "mercadolivre",
            "external_id": "ml1",
            "title": "Carro 1",
            "url": "https://example.com/1",
            "price": 50000,
            "year": 2020,
            "make": "Toyota",
            "model": "Corolla",
            "mileage_km": "100.000",
            "fuel_type": "gasoline",
            "transmission": "automatic",
            "version": "2.0",
            "seller_type": "dealer",
            "city": "São Paulo",
            "state": "SP",
            "color": "branco",
            "doors": 4,
            "body_type": "sedan",
            "listing_type": "marketplace",
        }
    ]

    ids = car_listings_repo.insert_ignore_duplicates_return_ids(db, payload1)
    assert len(ids) == 1

    # Get the initial updated_at
    from app.models.car_listing import CarListing
    row1 = db.query(CarListing).filter(CarListing.id == ids[0]).first()
    updated_at_1 = row1.updated_at

    # Verify deduping worked by checking there's only one row with this source/external_id
    all_rows = db.query(CarListing).filter(
        CarListing.source == "mercadolivre",
        CarListing.external_id == "ml1",
    ).all()
    assert len(all_rows) == 1, f"Expected 1 row, got {len(all_rows)}"

    # Sleep to ensure time passes
    time.sleep(0.1)

    # Upsert with identical data
    ids2 = car_listings_repo.insert_ignore_duplicates_return_ids(db, payload1)
    assert len(ids2) == 1
    assert ids2[0] == ids[0], f"Expected same ID {ids[0]}, got {ids2[0]}"

    # Check that updated_at hasn't changed
    row2 = db.query(CarListing).filter(CarListing.id == ids[0]).first()
    updated_at_2 = row2.updated_at

    assert updated_at_1 == updated_at_2, "updated_at should not change when all fields are identical"


def test_updated_at_changes_when_field_is_filled_from_null(db):
    """
    Upsert com um campo preenchendo um NULL → updated_at é atualizado.
    """
    # First insert with year=NULL
    payload1 = [
        {
            "source": "mercadolivre",
            "external_id": "ml2",
            "title": "Carro 2",
            "url": "https://example.com/2",
            "price": 60000,
            "year": None,  # NULL
            "make": "Honda",
            "model": "Civic",
            "mileage_km": "80.000",
            "fuel_type": "flex",
            "transmission": "automatic",
            "version": "1.8",
            "seller_type": "private",
            "city": "Rio de Janeiro",
            "state": "RJ",
            "color": "preto",
            "doors": 4,
            "body_type": "sedan",
            "listing_type": "marketplace",
        }
    ]

    ids = car_listings_repo.insert_ignore_duplicates_return_ids(db, payload1)
    assert len(ids) == 1

    # Get the initial updated_at
    from app.models.car_listing import CarListing
    row1 = db.query(CarListing).filter(CarListing.id == ids[0]).first()
    updated_at_1 = row1.updated_at
    assert row1.year is None

    # Sleep to ensure time passes
    time.sleep(0.1)

    # Upsert with year filled in
    payload2 = [
        {
            "source": "mercadolivre",
            "external_id": "ml2",
            "title": "Carro 2",
            "url": "https://example.com/2",
            "price": 60000,
            "year": 2019,  # Now filled
            "make": "Honda",
            "model": "Civic",
            "mileage_km": "80.000",
            "fuel_type": "flex",
            "transmission": "automatic",
            "version": "1.8",
            "seller_type": "private",
            "city": "Rio de Janeiro",
            "state": "RJ",
            "color": "preto",
            "doors": 4,
            "body_type": "sedan",
            "listing_type": "marketplace",
        }
    ]

    ids2 = car_listings_repo.insert_ignore_duplicates_return_ids(db, payload2)
    assert len(ids2) == 1
    assert ids2[0] == ids[0]

    # Check that updated_at has changed
    row2 = db.query(CarListing).filter(CarListing.id == ids[0]).first()
    updated_at_2 = row2.updated_at
    assert row2.year == 2019

    assert updated_at_2 > updated_at_1, "updated_at should change when a field is filled from NULL"


def test_updated_at_changes_when_url_differs(db):
    """
    Upsert com url diferente → updated_at é atualizado (url sempre atualiza).
    """
    # First insert
    payload1 = [
        {
            "source": "mercadolivre",
            "external_id": "ml3",
            "title": "Carro 3",
            "url": "https://example.com/3a",
            "price": 70000,
            "year": 2021,
            "make": "Ford",
            "model": "Focus",
            "mileage_km": "50.000",
            "fuel_type": "gasoline",
            "transmission": "manual",
            "version": "1.6",
            "seller_type": "dealer",
            "city": "Brasília",
            "state": "DF",
            "color": "prata",
            "doors": 4,
            "body_type": "hatchback",
            "listing_type": "marketplace",
        }
    ]

    ids = car_listings_repo.insert_ignore_duplicates_return_ids(db, payload1)
    assert len(ids) == 1

    # Get the initial updated_at
    from app.models.car_listing import CarListing
    row1 = db.query(CarListing).filter(CarListing.id == ids[0]).first()
    updated_at_1 = row1.updated_at

    # Sleep to ensure time passes
    time.sleep(0.1)

    # Upsert with different URL
    payload2 = [
        {
            "source": "mercadolivre",
            "external_id": "ml3",
            "title": "Carro 3",
            "url": "https://example.com/3b",  # Different URL
            "price": 70000,
            "year": 2021,
            "make": "Ford",
            "model": "Focus",
            "mileage_km": "50.000",
            "fuel_type": "gasoline",
            "transmission": "manual",
            "version": "1.6",
            "seller_type": "dealer",
            "city": "Brasília",
            "state": "DF",
            "color": "prata",
            "doors": 4,
            "body_type": "hatchback",
            "listing_type": "marketplace",
        }
    ]

    ids2 = car_listings_repo.insert_ignore_duplicates_return_ids(db, payload2)
    assert len(ids2) == 1
    assert ids2[0] == ids[0]

    # Check that updated_at has changed
    row2 = db.query(CarListing).filter(CarListing.id == ids[0]).first()
    updated_at_2 = row2.updated_at
    assert row2.url == "https://example.com/3b"

    assert updated_at_2 > updated_at_1, "updated_at should change when URL differs"
