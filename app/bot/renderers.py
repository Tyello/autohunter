from __future__ import annotations

from collections import defaultdict
import re
from typing import Iterable


def _format_int_safe(value: str) -> str | None:
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    clean = raw.replace("r$", "").replace("km", "").replace(".", "").replace(",", "")
    clean = re.sub(r"\D+", "", clean)
    if not clean:
        return None
    try:
        return f"{int(clean):,}".replace(",", ".")
    except Exception:
        return None


def _format_year_safe(value: str) -> str | None:
    raw = str(value or "")
    m = re.search(r"\b(19|20)\d{2}\b", raw)
    if not m:
        return None
    return m.group(0)


def _render_filter_label(field: str, operator: str, value: str) -> str:
    fallback = f"{field} {operator} {value}"
    if field == "price" and operator == "lte":
        parsed = _format_int_safe(value)
        return f"Preço até R$ {parsed}" if parsed else fallback
    if field == "price" and operator == "gte":
        parsed = _format_int_safe(value)
        return f"Preço a partir de R$ {parsed}" if parsed else fallback
    if field == "year" and operator == "lte":
        parsed = _format_year_safe(value)
        return f"Ano até {parsed}" if parsed else fallback
    if field == "year" and operator == "gte":
        parsed = _format_year_safe(value)
        return f"Ano a partir de {parsed}" if parsed else fallback
    if field == "mileage_km" and operator == "lte":
        parsed = _format_int_safe(value)
        return f"KM até {parsed}" if parsed else fallback
    if field == "city" and operator == "eq":
        return f"Cidade: {value}"
    if field == "state" and operator == "eq":
        return f"Estado: {value}"
    if field == "color" and operator == "eq":
        return f"Cor: {value}"
    if field == "source" and operator == "eq":
        return f"Fonte: {str(value).upper()}"
    return fallback


def _friendly_wishlist_filters(filters: list[dict]) -> list[str]:
    by_field: dict[str, dict[str, str]] = defaultdict(dict)
    passthrough: list[str] = []
    for f in filters or []:
        field = str(f.get("field") or "").strip()
        operator = str(f.get("operator") or "").strip()
        value = str(f.get("value") or "").strip()
        if not (field and operator):
            continue
        if field in {"price", "year"} and operator in {"gte", "lte"}:
            by_field[field][operator] = value
            continue
        passthrough.append(_render_filter_label(field, operator, value))

    labels: list[str] = []
    if "year" in by_field:
        lo, hi = _format_year_safe(by_field["year"].get("gte") or ""), _format_year_safe(by_field["year"].get("lte") or "")
        if lo and hi:
            labels.append(f"Ano entre {lo} e {hi}")
        elif lo:
            labels.append(f"Ano a partir de {lo}")
        elif hi:
            labels.append(f"Ano até {hi}")
        else:
            for op in ("gte", "lte"):
                if by_field["year"].get(op):
                    labels.append(_render_filter_label("year", op, by_field["year"][op]))
    if "price" in by_field:
        lo, hi = _format_int_safe(by_field["price"].get("gte") or ""), _format_int_safe(by_field["price"].get("lte") or "")
        if lo and hi:
            labels.append(f"Preço entre R$ {lo} e R$ {hi}")
        elif lo:
            labels.append(f"Preço a partir de R$ {lo}")
        elif hi:
            labels.append(f"Preço até R$ {hi}")
        else:
            for op in ("gte", "lte"):
                if by_field["price"].get(op):
                    labels.append(_render_filter_label("price", op, by_field["price"][op]))
    labels.extend(passthrough)
    return labels


def render_start_text(active_wishlists_count: int) -> str:
    if active_wishlists_count > 0:
        return (
            "👋 AutoHunter\n\n"
            "Seu monitoramento já está ativo.\n\n"
            "Use /menu para ver suas buscas, anúncios rastreados, plano atual ou fazer uma busca manual."
        )
    return (
        "👋 Bem-vindo ao AutoHunter\n\n"
        "Eu monitoro anúncios de carros usados para você.\n\n"
        "Você me diz o carro que procura, adiciona filtros como preço, ano, KM e região, e eu aviso aqui no Telegram quando aparecer algo compatível.\n\n"
        "Para começar:\n"
        "toque em /menu e depois em ➕ Criar busca."
    )


def render_user_wishlists(wishlists) -> str:
    if not wishlists:
        return (
            "Você ainda não criou nenhuma busca.\n\n"
            "Crie uma busca para eu monitorar anúncios de carros usados e te avisar quando aparecer algo compatível."
        )

    if isinstance(wishlists[0], dict):
        lines = ["🎯 Minhas buscas", ""]
        for item in wishlists:
            labels = _friendly_wishlist_filters(item.get("filters", []))
            shown = labels[:3]
            status = "ativa" if item.get("is_active", True) else "pausada"
            lines.extend([
                f"{item['index']}. {item['query']}",
                f"Status: {status}",
                "Filtros:",
            ])
            if shown:
                lines.extend([f"- {label}" for label in shown])
                if len(labels) > 3:
                    lines.append(f"- +{len(labels) - 3} filtros")
            else:
                lines.append("- Nenhum filtro")
            lines.extend([
                f"Anúncios rastreados: {item.get('tracked_count', 0)}/{item.get('tracked_limit', 3)}",
                f"Alertas enviados hoje: {item.get('notifications_24h_count', 0)}",
                "",
            ])
        lines.append("Escolha uma ação:")
        return "\n".join(lines).strip()

    lines = [f"{i + 1}. {x.query}" for i, x in enumerate(wishlists)]
    return "Minhas buscas:\n" + "\n".join(lines)



def render_all_tracked_listings(wishlists, tracked_messages: list[str], plan_usage: str | None = None) -> str:
    if not wishlists:
        return (
            "⭐ Anúncios rastreados\n\n"
            "Aqui ficam anúncios específicos que você quer acompanhar de perto.\n\n"
            "Busca salva = eu encontro novos anúncios para você.\n"
            "Anúncio rastreado = eu acompanho preço/status de um anúncio específico.\n\n"
            "Você ainda não rastreou nenhum anúncio.\n\n"
            "Quando receber ou encontrar um anúncio interessante, toque em ⭐ Rastrear para acompanhar preço e status."
        )

    lines = ["⭐ Anúncios rastreados", "", "Aqui ficam anúncios específicos que você quer acompanhar de perto.", "", "Busca salva = eu encontro novos anúncios para você.", "Anúncio rastreado = eu acompanho preço/status de um anúncio específico.", ""]
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
    header = "Filtros da busca:"
    if wishlist_query:
        header += f"\n🔎 {wishlist_query}"
    lines = [f"{i + 1}. {_fmt_filter(f)}" for i, f in enumerate(fs)]
    return f"{header}\n\n" + "\n".join(lines)


def render_help_text() -> str:
    return (
        "❓ Ajuda rápida\n\n"
        "• /menu — abrir o menu principal\n"
        "• ➕ Criar busca — monitorar um carro continuamente\n"
        "• 🎯 Minhas buscas — ver e gerenciar buscas salvas\n"
        "• ⭐ Anúncios rastreados — acompanhar anúncios específicos\n"
        "• 🔎 Buscar agora — busca pontual, sem salvar\n"
        "• /plan — ver uso e limites do seu plano\n"
        "• /upgrade — ver detalhes do Premium\n\n"
        "Dica: se quiser comandos avançados/legados, use /wishlist_help."
    )


def render_upgrade_text(has_payment_links: bool) -> str:
    text = (
        "🚀 AutoHunter Premium\n\n"
        "Escolha seu plano:\n\n"
        "Mensal\n"
        "De R$ 9,99 por R$ 5,99/mês no lançamento.\n\n"
        "Anual\n"
        "De R$ 89,99 por R$ 59,99/ano.\n"
        "Equivale a R$ 4,99/mês.\n\n"
        "Benefícios:\n"
        "- até 10 wishlists\n"
        "- até 5 anúncios rastreados no total\n"
        "- alertas automáticos de preço/status\n"
        "- até 15 notificações por dia por wishlist\n"
        "- prioridade em novas funcionalidades\n\n"
        "Após pagar, envie o comprovante aqui no Telegram.\n"
        "A ativação é feita manualmente."
    )
    if not has_payment_links:
        text += "\n\nOs links de pagamento ainda não estão configurados. Fale com o admin para ativação manual."
    return text


def build_upgrade_choice_keyboard(monthly_link: str | None, annual_link: str | None):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    buttons = []
    if monthly_link:
        buttons.append([InlineKeyboardButton("💳 Assinar Mensal", callback_data="UPGRADE:MONTHLY")])
    if annual_link:
        buttons.append([InlineKeyboardButton("💳 Assinar Anual", callback_data="UPGRADE:ANNUAL")])
    return InlineKeyboardMarkup(buttons) if buttons else None


def build_upgrade_payment_link_keyboard(*, plan_period: str, payment_link: str):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    label = "Abrir pagamento mensal" if plan_period == "monthly" else "Abrir pagamento anual"
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, url=payment_link)]])
