from __future__ import annotations

from typing import Iterable


def render_start_text(active_wishlists_count: int) -> str:
    base = (
        "👋 Bem-vindo ao AutoHunter\n\n"
        "Eu monitoro anúncios de carros para você e aviso no Telegram quando aparecer algo compatível com o que você procura.\n\n"
    )
    if active_wishlists_count > 0:
        return (
            base
            + f"Você já tem {active_wishlists_count} wishlist(s) ativa(s).\n\n"
            "Use /menu para ver suas buscas, filtros e anúncios rastreados."
        )

    return (
        base
        + "Você pode criar buscas, aplicar filtros, rastrear anúncios específicos e acompanhar mudanças de preço/status.\n\n"
        "Use /menu para começar pelo fluxo guiado."
    )


def render_user_wishlists(wishlists) -> str:
    if not wishlists:
        return (
            "Você não tem wishlists.\n"
            "Opções:\n"
            "• /wishlist_add (fluxo oficial)\n"
            "• /wishlist add <termos> (compatibilidade legado)"
        )

    if isinstance(wishlists[0], dict):
        lines = ["🎯 Suas wishlists", ""]
        for item in wishlists:
            status = "ativa" if item.get("is_active", True) else "inativa"
            lines.extend([
                f"{item['index']}. {item['query']}",
                f"Filtros: {item.get('filters_count', 0)}",
                f"Rastreados: {item.get('tracked_count', 0)}/{item.get('tracked_limit', 3)}",
                f"Notificações: {item.get('notifications_24h_count', 0)} nas últimas 24h",
                f"Status: {status}",
                "",
            ])
        lines.extend([
            "Comandos:",
            "Use /menu → ⚙️ Filtros para ajustar.",
            "Use /wishlist_track_list para ver rastreados.",
        ])
        return "\n".join(lines).strip()

    lines = [f"{i + 1}. {x.query}" for i, x in enumerate(wishlists)]
    return "Wishlists:\n" + "\n".join(lines)



def render_all_tracked_listings(wishlists, tracked_messages: list[str], plan_usage: str | None = None) -> str:
    if not wishlists:
        return "Você não tem wishlists. Use /wishlist_add para criar a primeira."

    lines = ["📌 Seus anúncios rastreados"]
    if plan_usage:
        lines.append(plan_usage)
    for msg in tracked_messages:
        lines.append("")
        lines.append(msg)
    return "\n".join(lines)


def render_wishlist_filters(filters: Iterable, wishlist_query: str | None = None) -> str:
    def _to_int_str(v: str) -> str:
        return f"{int(v):,}".replace(",", ".")

    def _fmt_filter(f) -> str:
        if f.field == "price" and f.operator == "lte":
            return f"Preço até R$ {_to_int_str(f.value)}"
        if f.field == "price" and f.operator == "gte":
            return f"Preço a partir de R$ {_to_int_str(f.value)}"
        if f.field == "year" and f.operator == "lte":
            return f"Ano até {int(f.value)}"
        if f.field == "year" and f.operator == "gte":
            return f"Ano a partir de {int(f.value)}"
        if f.field == "mileage_km":
            if f.operator == "lte":
                return f"KM até {_to_int_str(f.value)}"
            if f.operator == "gte":
                return f"KM a partir de {_to_int_str(f.value)}"
        if f.field == "city" and f.operator == "eq":
            return f"Cidade: {f.value}"
        if f.field == "state" and f.operator == "eq":
            return f"Estado: {f.value}"
        if f.field == "source" and f.operator == "eq":
            return f"Fonte: {f.value}"
        if f.field == "color" and f.operator == "eq":
            return f"Cor: {f.value}"
        if f.field == "seller_type":
            label = {"private": "particular", "dealer": "loja/revenda"}.get((f.value or "").lower(), f.value)
            if f.operator == "eq":
                return f"Vendedor: {label}"
            if f.operator == "neq":
                return f"Excluir vendedor: {label}"
        if f.field == "body_type":
            label = {"suv": "SUV", "convertible": "conversível"}.get((f.value or "").lower(), f.value)
            if f.operator == "eq":
                return f"Carroceria: {label}"
            if f.operator == "neq":
                return f"Excluir carroceria: {label}"
        if f.field == "doors":
            if f.operator == "eq":
                return f"Portas: {int(f.value)}"
            if f.operator == "neq":
                return f"Excluir portas: {int(f.value)}"
            if f.operator == "lte":
                return f"Portas até {int(f.value)}"
            if f.operator == "gte":
                return f"Portas a partir de {int(f.value)}"
            if f.operator == "between":
                lo_s, hi_s = [p.strip() for p in str(f.value).split(",", 1)]
                return f"Portas entre {int(lo_s)} e {int(hi_s)}"
        return f"{f.field} {f.operator} {f.value}"

    fs = list(filters)
    header = "Filtros da wishlist:"
    if wishlist_query:
        header += f"\n🔎 {wishlist_query}"
    lines = [f"{i + 1}. {_fmt_filter(f)}" for i, f in enumerate(fs)]
    return f"{header}\n\n" + "\n".join(lines)


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
        "• /menu → ⚙️ Filtros — adicionar, ver e remover filtros por botões\n"
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
