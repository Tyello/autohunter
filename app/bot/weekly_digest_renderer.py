from __future__ import annotations


def _truncate(text: str, max_len: int = 60) -> str:
    clean = (text or "Sem título").strip()
    if len(clean) <= max_len:
        return clean
    return clean[: max_len - 1].rstrip() + "…"


def _fmt_brl(price) -> str:
    if price is None:
        return "Preço indisponível"
    try:
        value = int(round(float(price)))
        return "R$ " + f"{value:,}".replace(",", ".")
    except Exception:
        return "Preço indisponível"


def render_weekly_digest(payload: dict) -> str:
    days = int(payload.get("days") or 7)
    totals = payload.get("totals") or {}
    sent = int(totals.get("sent") or 0)
    if sent == 0:
        return f"📬 Digest semanal — Garagem Alvo\n\nPeríodo: últimos {days} dias\n\nSem alertas enviados nos últimos {days} dias."

    lines = [
        "📬 Digest semanal — Garagem Alvo",
        "",
        f"Período: últimos {days} dias",
        "",
        "Resumo:",
        f"- alertas enviados: {sent}",
        f"- buscas com resultado: {int(totals.get('wishlists_with_results') or 0)}",
        f"- price drops: {int(totals.get('price_drops') or 0)}",
    ]

    top_items = (payload.get("top_opportunities") or [])[:5]
    if top_items:
        lines.extend(["", "Top oportunidades:"])
        for i, item in enumerate(top_items, 1):
            lines.append(f"{i}. {_truncate(item.get('title') or '')} — score {item.get('score_v2') if item.get('score_v2') is not None else '-'}")
            lines.append(f"   {_fmt_brl(item.get('price'))} | {(item.get('source') or '-').upper()} | Wishlist: {item.get('wishlist') or '-'}")

    drop_items = (payload.get("price_drops") or [])[:3]
    if drop_items:
        lines.extend(["", "Price drops:"])
        for item in drop_items:
            lines.append(f"- {_truncate(item.get('title') or '')} caiu para {_fmt_brl(item.get('price'))}")

    lines.extend(["", "Próximo passo:", "Use /wishlist para ajustar suas buscas."])
    return "\n".join(lines)


def render_weekly_digest_candidates(candidates: list[dict], *, days: int) -> str:
    if not candidates:
        return f"📬 Digest semanal — candidatos\n\nJanela: {days} dias\n\nNenhum usuário com alertas enviados nos últimos {days} dias."

    lines = [
        "📬 Digest semanal — candidatos",
        "",
        f"Janela: {days} dias",
        f"Candidatos: {len(candidates)}",
        "",
    ]
    for i, item in enumerate(candidates, 1):
        username = (item.get("username") or "-").strip()
        username = username if username.startswith("@") else f"@{username}"
        lines.extend(
            [
                f"[{i}] {username} / chat_id={item.get('telegram_chat_id')}",
                f"- alertas enviados: {int(item.get('total_sent') or 0)}",
                f"- buscas com resultado: {int(item.get('total_wishlists_with_results') or 0)}",
                f"- price drops: {int(item.get('total_price_drops') or 0)}",
                f"- top score: {item.get('top_score_v2') if item.get('top_score_v2') is not None else '-'}",
                f"- último alerta: {item.get('latest_sent_at') or '-'}",
            ]
        )
        wishlists = item.get("sample_wishlist_names") or []
        listings = item.get("sample_listing_titles") or []
        if wishlists:
            lines.append("- amostras de busca: " + ", ".join(_truncate(str(w), 24) for w in wishlists[:3]))
        if listings:
            lines.append("- amostras de anúncio: " + ", ".join(_truncate(str(t), 28) for t in listings[:3]))
        lines.append("")
    lines.extend(["Próximo passo:", "Use /admin digest user <chat_id> 7 para ver o preview individual."])
    return "\n".join(lines)
