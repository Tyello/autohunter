import time
from datetime import datetime, timezone

import pytest

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


def test_status_defaults_to_active_on_insert(db):
    """
    Insert novo → status == 'active', last_seen_at está perto de now()
    """
    from app.models.car_listing import CarListing

    payload = [
        {
            "source": "mercadolivre",
            "external_id": "ml_new",
            "title": "Carro Novo",
            "url": "https://example.com/new",
            "price": 45000,
            "year": 2022,
            "make": "Hyundai",
            "model": "HB20",
            "mileage_km": "30.000",
            "fuel_type": "gasoline",
            "transmission": "automatic",
            "version": "1.0",
            "seller_type": "dealer",
            "city": "Salvador",
            "state": "BA",
            "color": "vermelho",
            "doors": 4,
            "body_type": "hatchback",
            "listing_type": "marketplace",
        }
    ]

    # Use UTC for comparison since server_default=now() returns UTC time
    before_insert = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)  # naive UTC datetime for comparison
    ids = car_listings_repo.insert_ignore_duplicates_return_ids(db, payload)
    after_insert = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=999999)

    assert len(ids) == 1

    row = db.query(CarListing).filter(CarListing.id == ids[0]).first()
    assert row.status == 'ativo', "status should default to 'ativo'"
    assert row.last_seen_at is not None, "last_seen_at should not be null"
    # Strip timezone for comparison if needed (for SQLite compatibility)
    last_seen = row.last_seen_at
    if last_seen.tzinfo is not None:
        last_seen = last_seen.replace(tzinfo=None)
    assert before_insert <= last_seen <= after_insert, "last_seen_at should be around insertion time"


def test_status_check_constraint_rejects_invalid_value(db):
    """
    REQ-004: a CHECK constraint deve rejeitar qualquer status fora de
    {'ativo','suspeito','inativo'} — mirrorada em __table_args__ do model,
    já que o schema de teste é criado via Base.metadata.create_all (não via
    migração Alembic), então só a constraint da migração não seria exercitada.
    """
    from sqlalchemy.exc import IntegrityError

    from app.models.car_listing import CarListing

    row = CarListing(
        source="mercadolivre",
        external_id="ml_invalid_status",
        title="Carro",
        url="https://example.com/invalid",
        status="banana",
    )
    db.add(row)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_status_resets_to_active_on_upsert_when_inactive(db):
    """
    Update de linha existente com status='inactive' → após upsert, status volta a 'active' e last_seen_at avança
    """
    from app.models.car_listing import CarListing
    from sqlalchemy import update

    # First insert
    payload1 = [
        {
            "source": "mercadolivre",
            "external_id": "ml_inactive",
            "title": "Carro Inativo",
            "url": "https://example.com/inactive",
            "price": 55000,
            "year": 2020,
            "make": "Volkswagen",
            "model": "Gol",
            "mileage_km": "120.000",
            "fuel_type": "flex",
            "transmission": "manual",
            "version": "1.0",
            "seller_type": "private",
            "city": "Curitiba",
            "state": "PR",
            "color": "cinza",
            "doors": 4,
            "body_type": "hatchback",
            "listing_type": "marketplace",
        }
    ]

    ids = car_listings_repo.insert_ignore_duplicates_return_ids(db, payload1)
    assert len(ids) == 1

    row1 = db.query(CarListing).filter(CarListing.id == ids[0]).first()
    assert row1.status == 'ativo'
    last_seen_at_1 = row1.last_seen_at

    # Manually set status to 'inativo'
    db.execute(update(CarListing).where(CarListing.id == ids[0]).values(status='inativo'))
    db.commit()

    row_inactive = db.query(CarListing).filter(CarListing.id == ids[0]).first()
    assert row_inactive.status == 'inativo'

    # Sleep to ensure time passes
    time.sleep(0.1)

    # Upsert with same data
    ids2 = car_listings_repo.insert_ignore_duplicates_return_ids(db, payload1)
    assert len(ids2) == 1
    assert ids2[0] == ids[0]

    # Check that status is back to 'ativo' and last_seen_at advanced
    row2 = db.query(CarListing).filter(CarListing.id == ids[0]).first()
    assert row2.status == 'ativo', "status should be reset to 'ativo' on upsert"
    assert row2.last_seen_at > last_seen_at_1, "last_seen_at should advance on upsert"


def test_last_seen_at_updates_without_changing_updated_at(db):
    """
    Dois upserts consecutivos sem mudança → updated_at NÃO muda, mas last_seen_at MUDA
    """
    from app.models.car_listing import CarListing

    payload = [
        {
            "source": "mercadolivre",
            "external_id": "ml_liveness",
            "title": "Carro Liveness",
            "url": "https://example.com/liveness",
            "price": 65000,
            "year": 2021,
            "make": "Chevrolet",
            "model": "Onix",
            "mileage_km": "60.000",
            "fuel_type": "flex",
            "transmission": "automatic",
            "version": "1.0",
            "seller_type": "dealer",
            "city": "Recife",
            "state": "PE",
            "color": "azul",
            "doors": 4,
            "body_type": "sedan",
            "listing_type": "marketplace",
        }
    ]

    # First insert
    ids = car_listings_repo.insert_ignore_duplicates_return_ids(db, payload)
    assert len(ids) == 1

    row1 = db.query(CarListing).filter(CarListing.id == ids[0]).first()
    updated_at_1 = row1.updated_at
    last_seen_at_1 = row1.last_seen_at

    # Sleep to ensure time passes
    time.sleep(0.1)

    # Second upsert with identical data
    ids2 = car_listings_repo.insert_ignore_duplicates_return_ids(db, payload)
    assert len(ids2) == 1
    assert ids2[0] == ids[0]

    row2 = db.query(CarListing).filter(CarListing.id == ids[0]).first()
    updated_at_2 = row2.updated_at
    last_seen_at_2 = row2.last_seen_at

    assert updated_at_1 == updated_at_2, "updated_at should not change when all fields are identical"
    assert last_seen_at_2 > last_seen_at_1, "last_seen_at should advance on every upsert"
