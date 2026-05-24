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


def _fmt_km(km) -> str:
    if km is None:
        return "km indisponível"
    try:
        value = int(round(float(km)))
        return f"{value:,}".replace(",", ".") + " km"
    except Exception:
        return "km indisponível"


def _fmt_location(item: dict) -> str:
    city = (item.get("city") or "").strip()
    state = (item.get("state") or "").strip()
    location = (item.get("location") or "").strip()
    if city and state:
        return f"{city}/{state}"
    if state:
        return state
    if city:
        return city
    if location:
        return location
    return "local indisponível"


def _fmt_score(score) -> str:
    if score is None:
        return "-"
    try:
        return str(int(round(float(score))))
    except Exception:
        return "-"


def render_weekly_digest(payload: dict) -> str:
    days = int(payload.get("days") or 7)
    totals = payload.get("totals") or {}
    sent = int(totals.get("sent") or 0)
    if sent == 0:
        return (
            "📬 Digest semanal — Garagem Alvo\n\n"
            f"Período: últimos {days} dias\n\n"
            "Nenhum alerta enviado nesse período.\n"
            "Suas buscas continuam ativas.\n"
            "Use /wishlist para revisar filtros ou /buscar para testar uma busca pontual."
        )

    source_names = [str(item.get("source") or "-").upper() for item in (payload.get("by_source") or [])[:5] if item.get("source")]
    lines = [
        "📬 Digest semanal — Garagem Alvo",
        "",
        f"Período: últimos {days} dias",
        "",
        "Resumo:",
        f"- alertas enviados: {sent}",
        f"- buscas com resultado: {int(totals.get('wishlists_with_results') or 0)}",
        f"- fontes: {', '.join(source_names) if source_names else '-'}",
        f"- price drops: {int(totals.get('price_drops') or 0)}",
    ]

    top_items = (payload.get("top_opportunities") or [])[:5]
    if top_items:
        lines.extend(["", "🏁 Top oportunidades"])
        for i, item in enumerate(top_items, 1):
            title = _truncate(item.get("title") or "", 64)
            year = item.get("year")
            if year and str(year) not in title:
                title = f"{title} {year}"
            rarity = item.get('rarity_context') or {}
            badge = ''
            if rarity.get('is_rare'):
                if rarity.get('label') == 'raro':
                    badge = ' | 🧬 raro'
                elif rarity.get('label') == 'incomum':
                    badge = ' | 🧬 incomum'
            lines.append(f"{i}. {title} — score {_fmt_score(item.get('score_v2'))}{badge}")
            lines.append(f"   {_fmt_brl(item.get('price'))} | {_fmt_km(item.get('mileage_km'))} | {_fmt_location(item)}")
            lines.append(f"   Busca: {item.get('wishlist') or '-'}")
            lines.append(f"   Fonte: {(item.get('source') or '-').upper()}")

    rare_items = (payload.get("rare_opportunities") or [])[:3]
    if rare_items:
        lines.extend(["", "🧬 Achados raros"])
        for item in rare_items:
            label = (item.get('rarity_context') or {}).get('label')
            suffix = 'raro no histórico recente' if label == 'raro' else 'configuração incomum'
            lines.append(f"- {_truncate(item.get('title') or '', 64)} — {suffix}")
            lines.append(f"  Score {_fmt_score(item.get('score_v2'))} | {_fmt_brl(item.get('price'))} | {_fmt_location(item)}")
            lines.append(f"  Busca: {item.get('wishlist') or '-'}")

    drop_items = (payload.get("price_drops") or [])[:3]
    if drop_items:
        lines.extend(["", "📉 Quedas de preço"])
        for item in drop_items:
            lines.append(f"- {_truncate(item.get('title') or '', 64)} caiu para {_fmt_brl(item.get('price'))}")

    top_wishlists = (payload.get("by_wishlist") or [])[:5]
    if top_wishlists:
        lines.extend(["", "🔎 Buscas com mais alertas"])
        for item in top_wishlists:
            lines.append(f"- {item.get('wishlist') or '-'}: {int(item.get('count') or 0)}")

    lines.extend(["", "Próximo passo:", "Use /digest preview para rever quando quiser.", "Use /wishlist para ajustar suas buscas."])
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
