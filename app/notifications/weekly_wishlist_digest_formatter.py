from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.services.weekly_wishlist_digest_service import WeeklyDigestUser


def _fmt_price(price: Decimal | None) -> str:
    if price is None:
        return "Preço n/d"
    try:
        return f"R$ {float(price):,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return f"R$ {price}"


def _fmt_dt(dt: datetime) -> str:
    return dt.strftime("%d/%m %H:%M")


def _wishlist_block(item) -> str:
    lines = [
        f"🔎 Busca: {item.query}",
    ]

    if not item.latest_listings:
        lines.extend(
            [
                "Monitorei anúncios na semana, mas nenhum está ativo dentro dos seus critérios agora.",
                "Continuo monitorando. Aviso quando aparecer algo bom.",
            ]
        )
        return "\n".join(lines)

    lines.append(f"Anúncios ativos agora: {item.total_active}")
    lines.append("Mais recentes que continuam no radar:")
    for i, listing in enumerate(item.latest_listings, start=1):
        title = (listing.title or "Sem título").strip()
        lines.append(
            f"{i}) {title}\n"
            f"   {_fmt_price(listing.price)} • {(listing.location or 'Local n/d')} • {listing.source}\n"
            f"   visto em {_fmt_dt(listing.last_seen_at)}\n"
            f"   {listing.url}"
        )
    return "\n".join(lines)


def format_weekly_wishlist_digest(user_digest: WeeklyDigestUser, *, max_chars: int = 3600) -> list[str]:
    total_wishlists = len(user_digest.wishlists)
    total_active = sum(max(int(item.total_active or 0), 0) for item in user_digest.wishlists)
    header = (
        "📋 Resumo da semana — Garagem Alvo\n"
        f"Monitorei {total_wishlists} busca(s). "
        f"{total_active} anúncio(s) seguem ativos no radar agora."
    )
    blocks = [_wishlist_block(item) for item in user_digest.wishlists]

    chunks: list[str] = []
    current = header

    for block in blocks:
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= max_chars:
            current = candidate
            continue

        if current:
            chunks.append(current)
        if len(block) <= max_chars:
            current = block
            continue

        # Fallback hard-split when one block is too large.
        start = 0
        while start < len(block):
            end = min(len(block), start + max_chars)
            piece = block[start:end]
            chunks.append(piece)
            start = end
        current = ""

    if current:
        chunks.append(current)

    return chunks
