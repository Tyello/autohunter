from __future__ import annotations


def render_user_wishlists(wishlists) -> str:
    if not wishlists:
        return (
            "Você não tem wishlists.\n"
            "Opções:\n"
            "• /wishlist_add (fluxo oficial)\n"
            "• /wishlist add <termos> (compatibilidade legado)"
        )
    lines = [f"{i + 1}. {x.query}" for i, x in enumerate(wishlists)]
    return "Wishlists:\n" + "\n".join(lines)


def render_all_tracked_listings(wishlists, tracked_messages: list[str]) -> str:
    if not wishlists:
        return "Você não tem wishlists. Use /wishlist_add para criar a primeira."

    lines = ["📌 Seus anúncios rastreados"]
    for msg in tracked_messages:
        lines.append("")
        lines.append(msg)
    return "\n".join(lines)


def render_help_text() -> str:
    return (
        "📌 Comandos do AutoHunter\n\n"
        "Wishlist:\n"
        "• /wishlist — listar\n"
        "• /wishlist_add — criar (assistente)\n"
        "• /menu → ➕ Criar wishlist — criar passo a passo\n"
        "• /wishlist_remove — remover\n"
        "• /wishlist_clear — limpar tudo\n\n"
        "Filtros (por wishlist):\n"
        "• /wishlist_filter_list <n>\n"
        "• /wishlist_filter_add <n> <campo> <op> <valor>\n"
        "• /wishlist_filter_remove <n> <k>\n\n"
        "Rastreamento por wishlist:\n"
        "• /wishlist_track_add <n> <url|external_id>\n"
        "• /wishlist_track_list <n>\n"
        "• /wishlist_track_remove <n> <slot>\n\n"
        "Quando receber um anúncio de uma wishlist, clique em ⭐ Rastrear para acompanhar preço e status.\n"
        "Veja seus rastreados com:\n"
        "/wishlist_track_list\n\n"
        "Campos: price | year | mileage_km | doors | source | color | city | state | seller_type | body_type (aliases body_type: carroceria, tipo_carroceria, categoria, estilo)\n"
        "Ops price/year/mileage_km/doors: lt lte gt gte eq neq between (alias: entre)\n"
        "Ops source/color/city/state/seller_type/body_type: eq neq (aliases: igual/=, apenas/somente, excluir/diferente/!=)\n"
        "Fontes (source): mercadolivre | olx | webmotors | chavesnamao | gogarage | icarros | mobiauto | kavak | facebook_marketplace\n\n"
        "Exemplos:\n"
        "• /wishlist_filter_add 1 year lte 2005\n"
        "• /wishlist_filter_add 1 price lte 90000\n"
        "• /wishlist_filter_add 1 km <= 80000\n"
        "• /wishlist_filter_add 1 km entre 30000 90000\n"
        "• /wishlist_filter_add 1 source eq olx\n"
        "• /wishlist_filter_add 1 color eq preto\n"
        "• /wishlist_filter_add 1 state eq SP\n"
        "• /wishlist_filter_add 1 vendedor = particular\n"
        "• /wishlist_filter_add 1 vendedor excluir loja\n\n"
        "• /wishlist_filter_add 1 carroceria = suv\n"
        "• /wishlist_filter_add 1 carroceria excluir pickup\n\n"
        "• /wishlist_filter_add 1 portas = 4\n"
        "• /wishlist_filter_add 1 portas >= 4\n"
        "• /wishlist_filter_add 1 portas entre 2 4\n\n"
        "Dica (atalho no /wishlist_add):\n"
        "• \"daihatsu cuore até 2005\" (cria filtro year lte 2005 automaticamente)\n\n"
        "Busca manual:\n"
        "• /buscar civic 2019 até 90000 sp\n\n"
        "Menu guiado:\n"
        "• /menu\n\n"
        "Alertas:\n"
        "• /alertas\n\n"
        "Planos:\n"
        "• /plan\n"
        "• /upgrade\n\n"
        "Sistema:\n"
        "• /status\n"
        "• /version\n"
        "• /me"
    )
