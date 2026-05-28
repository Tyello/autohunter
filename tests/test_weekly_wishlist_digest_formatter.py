from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import uuid

from app.notifications.weekly_wishlist_digest_formatter import format_weekly_wishlist_digest
from app.services.weekly_wishlist_digest_service import (
    WeeklyDigestListing,
    WeeklyDigestUser,
    WeeklyDigestWishlist,
)


def test_weekly_digest_formatter_includes_sections_and_totals():
    listing = WeeklyDigestListing(
        listing_id=uuid.uuid4(),
        title="Civic Touring",
        url="https://example/1",
        price=Decimal("99900"),
        location="Curitiba-PR",
        source="olx",
        created_at=datetime.now(timezone.utc),
        last_seen_at=datetime(2026, 1, 4, 10, 0, tzinfo=timezone.utc),
    )
    digest = WeeklyDigestUser(
        user_id=uuid.uuid4(),
        telegram_chat_id=1,
        wishlists=[
            WeeklyDigestWishlist(
                wishlist_id=uuid.uuid4(),
                query="civic",
                total_active=1,
                latest_listings=[listing],
            )
        ],
    )

    chunks = format_weekly_wishlist_digest(digest)

    assert len(chunks) == 1
    text = chunks[0]
    assert "Resumo da semana" in text
    assert "Garagem Alvo" in text
    assert "Busca: civic" in text
    assert "Anúncios ativos agora: 1" in text
    assert "Civic Touring" in text


def test_weekly_digest_formatter_explains_silence_when_no_active_results():
    digest = WeeklyDigestUser(
        user_id=uuid.uuid4(),
        telegram_chat_id=1,
        wishlists=[
            WeeklyDigestWishlist(
                wishlist_id=uuid.uuid4(),
                query="civic si manual",
                total_active=0,
                latest_listings=[],
            )
        ],
    )

    text = format_weekly_wishlist_digest(digest)[0]

    assert "Monitorei anúncios na semana" in text
    assert "Continuo monitorando" in text
    assert "Aviso quando aparecer algo bom" in text


def test_weekly_digest_formatter_splits_when_too_large():
    listings = [
        WeeklyDigestListing(
            listing_id=uuid.uuid4(),
            title=f"Carro muito longo {i} " + ("x" * 200),
            url=f"https://example/{i}",
            price=Decimal("50000"),
            location="SP",
            source="olx",
            created_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc),
        )
        for i in range(3)
    ]
    digest = WeeklyDigestUser(
        user_id=uuid.uuid4(),
        telegram_chat_id=1,
        wishlists=[
            WeeklyDigestWishlist(
                wishlist_id=uuid.uuid4(),
                query="hatch",
                total_active=3,
                latest_listings=listings,
            ),
            WeeklyDigestWishlist(
                wishlist_id=uuid.uuid4(),
                query="sedan",
                total_active=0,
                latest_listings=[],
            ),
        ],
    )

    chunks = format_weekly_wishlist_digest(digest, max_chars=500)
    assert len(chunks) >= 2
    assert all(len(c) <= 500 for c in chunks)
