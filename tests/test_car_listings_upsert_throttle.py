"""Throttle de last_seen_at no upsert de car_listings (SPEC 010, D3 / REQ-002..REQ-004).

Linhas vistas de novo dentro da janela de 30 min, sem mudança de campo e já `ativo`, não são
reescritas (o WHERE do ON CONFLICT DO UPDATE as pula). O retorno público do repo continua
contendo todas as linhas de entrada (`ids`), e `upserted` = total de linhas distintas.

Asserções de `inserted_new`/`updated` dependem de `xmax` (PostgreSQL). No SQLite o ramo de
stats é zerado por contrato; esses casos têm marker `postgres` (pulados sem TEST_DATABASE_URL).
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import update

from app.models.car_listing import CarListing
from app.repositories import car_listings_repo


def _payload(ext: str, **over) -> dict:
    base = {
        "source": "olx",
        "external_id": ext,
        "title": f"Carro {ext} bom",
        "url": f"https://example.test/olx/{ext}",
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
    base.update(over)
    return base


def _row(db, row_id):
    db.expire_all()
    return db.query(CarListing).filter(CarListing.id == row_id).first()


def test_identical_reupsert_within_window_does_not_write_row(db):
    # (a) REQ-002: revisto dentro de 30 min, sem mudança → last_seen_at e updated_at intactos
    ids = car_listings_repo.insert_ignore_duplicates_return_ids(db, [_payload("t_a")])
    before = _row(db, ids[0])
    last_seen_before, updated_before = before.last_seen_at, before.updated_at

    time.sleep(0.05)
    ids2 = car_listings_repo.insert_ignore_duplicates_return_ids(db, [_payload("t_a")])

    assert ids2 == ids
    after = _row(db, ids[0])
    assert after.last_seen_at == last_seen_before
    assert after.updated_at == updated_before


def test_identical_reupsert_within_window_still_reports_id_and_upserted(db):
    # (a) contrato de retorno: id continua em `ids`; upserted conta a linha mesmo pulada
    ids = car_listings_repo.insert_ignore_duplicates_return_ids(db, [_payload("t_a2")])
    res = car_listings_repo.insert_ignore_duplicates_return_ids(db, [_payload("t_a2")], with_stats=True)

    assert res["ids"] == ids
    assert res["upserted"] == 1


@pytest.mark.postgres
def test_identical_reupsert_within_window_stats_postgres(db):
    # (a) PostgreSQL: pulada conta como atualizada (não inserida)
    car_listings_repo.insert_ignore_duplicates_return_ids(db, [_payload("t_a3")])
    res = car_listings_repo.insert_ignore_duplicates_return_ids(db, [_payload("t_a3")], with_stats=True)

    assert res["upserted"] == 1
    assert res["inserted_new"] == 0
    assert res["updated"] == 1


def test_stale_last_seen_is_refreshed_and_status_active(db):
    # (b) REQ-004: last_seen_at com 31 min → upsert atualiza last_seen_at, mantém ativo
    ids = car_listings_repo.insert_ignore_duplicates_return_ids(db, [_payload("t_b1")])
    old = datetime.now(timezone.utc) - timedelta(minutes=31)
    db.execute(update(CarListing).where(CarListing.id == ids[0]).values(last_seen_at=old))
    db.commit()
    stale = _row(db, ids[0])
    last_seen_stale = stale.last_seen_at

    car_listings_repo.insert_ignore_duplicates_return_ids(db, [_payload("t_b1")])

    row = _row(db, ids[0])
    assert row.last_seen_at > last_seen_stale
    assert row.status == "ativo"


def test_inactive_row_seen_within_window_is_reactivated(db):
    # (b) REQ-004: inativo com last_seen_at recente → upsert reativa para ativo
    ids = car_listings_repo.insert_ignore_duplicates_return_ids(db, [_payload("t_b2")])
    db.execute(update(CarListing).where(CarListing.id == ids[0]).values(status="inativo"))
    db.commit()
    assert _row(db, ids[0]).status == "inativo"

    res = car_listings_repo.insert_ignore_duplicates_return_ids(db, [_payload("t_b2")], with_stats=True)

    assert res["ids"] == ids
    assert _row(db, ids[0]).status == "ativo"


def test_changed_field_within_window_is_written(db):
    # (c) campo mudou dentro da janela → linha é atualizada e updated_at muda
    ids = car_listings_repo.insert_ignore_duplicates_return_ids(db, [_payload("t_c")])
    before = _row(db, ids[0])
    updated_before = before.updated_at

    time.sleep(0.05)
    car_listings_repo.insert_ignore_duplicates_return_ids(
        db, [_payload("t_c", url="https://example.test/olx/t_c?novo=1")]
    )

    row = _row(db, ids[0])
    assert row.url == "https://example.test/olx/t_c?novo=1"
    assert row.updated_at > updated_before


def test_mixed_batch_returns_all_ids_and_counts_upserted(db):
    # (d) REQ-003: lote misto = 1 novo + 1 pulado (dentro da janela) + 1 mudou
    skipped_ids = car_listings_repo.insert_ignore_duplicates_return_ids(db, [_payload("t_d_skip")])
    changed_ids = car_listings_repo.insert_ignore_duplicates_return_ids(db, [_payload("t_d_chg")])

    batch = [
        _payload("t_d_new"),
        _payload("t_d_skip"),
        _payload("t_d_chg", url="https://example.test/olx/t_d_chg?v=2"),
    ]
    res = car_listings_repo.insert_ignore_duplicates_return_ids(db, batch, with_stats=True)

    assert len(res["ids"]) == 3
    assert skipped_ids[0] in res["ids"]
    assert changed_ids[0] in res["ids"]
    assert res["upserted"] == 3


@pytest.mark.postgres
def test_mixed_batch_stats_postgres(db):
    # (d) PostgreSQL: inserted_new conta só os inseridos
    car_listings_repo.insert_ignore_duplicates_return_ids(db, [_payload("t_d2_skip")])
    car_listings_repo.insert_ignore_duplicates_return_ids(db, [_payload("t_d2_chg")])

    batch = [
        _payload("t_d2_new"),
        _payload("t_d2_skip"),
        _payload("t_d2_chg", url="https://example.test/olx/t_d2_chg?v=2"),
    ]
    res = car_listings_repo.insert_ignore_duplicates_return_ids(db, batch, with_stats=True)

    assert res["upserted"] == 3
    assert res["inserted_new"] == 1
    assert res["updated"] == 2
