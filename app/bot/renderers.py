from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import re
from typing import Iterable

from app.sources.auctions.registry import get_auction_source_definition


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


def _filter_attr(f, key: str, default=None):
    if isinstance(f, dict):
        return f.get(key, default)
    return getattr(f, key, default)


def _friendly_wishlist_filters(filters: list[dict]) -> list[str]:
    by_field: dict[str, dict[str, str]] = defaultdict(dict)
    passthrough: list[str] = []
    for f in filters or []:
        field = str(_filter_attr(f, "field") or "").strip()
        operator = str(_filter_attr(f, "operator") or "").strip()
        value = str(_filter_attr(f, "value") or "").strip()
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
            labels.append(f"Ano {lo}" if lo == hi else f"Ano entre {lo} e {hi}")
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


def render_start_text(active_wishlists_count: int, *, context_line: str | None = None) -> str:
    if active_wishlists_count > 0:
        lines = [
            "👋 Garagem Alvo",
            "",
            "Seu monitoramento já está ativo.",
            "",
            f"Você tem {active_wishlists_count} busca(s) ativa(s).",
        ]
        if context_line:
            lines.append(context_line)
        lines.extend([
            "",
            "Use o botão abaixo ou /menu para ver suas buscas, anúncios rastreados, plano atual ou fazer uma busca manual.",
        ])
        return "\n".join(lines)
    return (
        "👋 Bem-vindo ao Garagem Alvo\n\n"
        "O buscador do entusiasta.\n\n"
        "Crie buscas para carros especiais, versões raras e boas bases de projeto.\n"
        "A gente monitora anúncios e te avisa aqui no Telegram quando aparecer algo compatível.\n\n"
        "Para começar:\n"
        "toque no botão abaixo e crie sua primeira busca."
    )


def _plural_pt(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def _to_int_safe(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _render_usage_bar(current: int, limit: int, width: int = 10) -> str:
    safe_width = max(_to_int_safe(width, 10), 1)
    safe_limit = _to_int_safe(limit, 0)
    if safe_limit <= 0:
        return "─" * safe_width

    safe_current = _to_int_safe(current, 0)
    clamped_current = min(max(safe_current, 0), safe_limit)
    filled = round((clamped_current / safe_limit) * safe_width)
    filled = min(max(filled, 0), safe_width)
    return ("█" * filled) + ("░" * (safe_width - filled))


def render_plan_text(
    *,
    plan_code: str,
    premium: bool,
    total_wishlists: int,
    max_wishlists: int,
    total_tracked: int,
    max_tracked: int,
    daily_notifications_per_wishlist: int,
    current_period_end=None,
) -> str:
    plan_name = "Premium" if premium else "Free"
    safe_total_wishlists = max(_to_int_safe(total_wishlists), 0)
    safe_max_wishlists = max(_to_int_safe(max_wishlists), 0)
    safe_total_tracked = max(_to_int_safe(total_tracked), 0)
    safe_max_tracked = max(_to_int_safe(max_tracked), 0)
    safe_daily = max(_to_int_safe(daily_notifications_per_wishlist), 0)

    lines = [
        f"📦 Seu plano: {plan_name}",
        "",
        "Uso atual:",
        "Buscas salvas",
        f"{safe_total_wishlists}/{safe_max_wishlists}",
        _render_usage_bar(safe_total_wishlists, safe_max_wishlists),
        "",
        "Anúncios rastreados",
        f"{safe_total_tracked}/{safe_max_tracked}",
        _render_usage_bar(safe_total_tracked, safe_max_tracked),
        "",
        "Alertas",
        f"Até {safe_daily} por dia por busca",
    ]

    if premium:
        valid_until = "—"
        if current_period_end:
            try:
                valid_until = current_period_end.astimezone(timezone.utc).strftime("%d/%m/%Y")
            except Exception:
                valid_until = "—"
        lines.extend(["", f"Válido até: {valid_until}", "Renovação: manual"])
        return "\n".join(lines)

    wishlist_remaining = max(safe_max_wishlists - safe_total_wishlists, 0)
    tracked_remaining = max(safe_max_tracked - safe_total_tracked, 0)
    if wishlist_remaining <= 0:
        lines.append("")
        lines.append("Você atingiu o limite de buscas salvas do Free.")
    else:
        lines.append("")
        lines.append(
            f"Você ainda tem {wishlist_remaining} busca(s) salva(s) disponível(is)."
        )

    if tracked_remaining <= 0:
        lines.append("Você atingiu o limite de anúncios rastreados do Free.")
    else:
        lines.append(
            f"Você ainda tem {tracked_remaining} anúncio(s) rastreado(s) disponível(is)."
        )

    lines.extend(
        [
            "Com Premium, você libera mais buscas, mais rastreados e mais alertas por dia.",
            "",
            "Para ver os planos: /upgrade",
        ]
    )
    return "\n".join(lines)


def render_user_wishlists(wishlists) -> str:
    if not wishlists:
        return (
            "Você ainda não criou nenhuma busca.\n\n"
            "Crie uma busca para eu monitorar anúncios de carros usados e te avisar quando aparecer algo compatível."
        )

    if isinstance(wishlists[0], dict):
        lines = ["🎯 Minhas buscas", ""]
        for item in wishlists:
            status_icon = "✅" if item.get("is_active", True) else "⏸️"
            labels = _friendly_wishlist_filters(item.get("filters", []))
            parts = [_plural_pt(len(labels), "filtro", "filtros") if labels else "sem filtros"]

            tracked_count = int(item.get("tracked_count", 0) or 0)
            if tracked_count > 0:
                parts.append(_plural_pt(tracked_count, "rastreado", "rastreados"))

            notifications_24h_count = int(item.get("notifications_24h_count", 0) or 0)
            if notifications_24h_count > 0:
                parts.append(_plural_pt(notifications_24h_count, "alerta hoje", "alertas hoje"))

            lines.append(f"{status_icon} {item['index']}. {item['query']} • " + " • ".join(parts))
        lines.extend(["", "Escolha uma busca para gerenciar:"])
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

    slot_lines: list[str] = []
    for message in tracked_messages or []:
        for raw_line in str(message or "").splitlines():
            line = raw_line.strip()
            if line.lower().startswith("slot "):
                slot_lines.append(line.lower())

    has_slot_details = bool(slot_lines)
    all_slots_empty = has_slot_details and all("vazio" in line for line in slot_lines)
    if tracked_messages and all_slots_empty:
        return (
            "⭐ Anúncios rastreados\n\n"
            "Você ainda não está acompanhando nenhum anúncio.\n\n"
            "Quando receber um alerta ou fizer uma busca, toque em ⭐ Rastrear para acompanhar preço e status daquele anúncio."
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
    year_gte = next((f for f in fs if f.field == "year" and f.operator == "gte"), None)
    year_lte = next((f for f in fs if f.field == "year" and f.operator == "lte"), None)
    skip_ids: set[int] = set()
    friendly_lines: list[str] = []
    if year_gte and year_lte:
        try:
            lo = int(year_gte.value)
            hi = int(year_lte.value)
            if lo == hi:
                friendly_lines.append(f"Ano {lo}")
                skip_ids.update({id(year_gte), id(year_lte)})
        except Exception:
            pass

    header = "Filtros da busca:"
    if wishlist_query:
        header += f"\n🔎 {wishlist_query}"
    entries = friendly_lines + [_fmt_filter(f) for f in fs if id(f) not in skip_ids]
    lines = [f"{i + 1}. {line}" for i, line in enumerate(entries)]
    return f"{header}\n\n" + "\n".join(lines)


def render_help_text() -> str:
    return (
        "❓ Ajuda rápida — Garagem Alvo\n\n"
        "• /menu — abrir o menu principal\n"
        "• ➕ Criar busca — monitorar um carro continuamente\n"
        "• 🎯 Minhas buscas — ver e gerenciar buscas salvas\n"
        "• ⭐ Anúncios rastreados — acompanhar anúncios específicos\n"
        "• 🔎 Buscar agora — busca pontual, sem salvar\n"
        "• /plan — ver uso e limites do seu plano\n"
        "• /digest — status, ativar/desativar e preview do digest semanal\n"
        "• /upgrade — ver detalhes do Premium\n\n"
        "Você pode ativar leilões em uma busca para receber oportunidades de fontes compatíveis, começando por VIP Leilões.\n"
        "Em leilões, lance não é preço final: confira edital, taxas/comissão, documentação e vistoria.\n\n"
        "Dica: se quiser comandos avançados/legados, use /wishlist_help."
    )


def _fmt_money_br(value) -> str | None:
    if value is None:
        return None
    try:
        if isinstance(value, Decimal):
            parsed = value
        elif isinstance(value, str):
            parsed = Decimal(value.strip())
        else:
            parsed = Decimal(str(value))
        return f"R$ {parsed:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (InvalidOperation, ValueError, TypeError):
        return None
    except Exception:
        return None


def _fmt_int_br(value) -> str | None:
    if value is None:
        return None
    try:
        return f"{int(value):,}".replace(",", ".")
    except Exception:
        return None


def _fmt_dt_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def render_admin_auction_lot(lot) -> str:
    title = str(getattr(lot, "title", None) or "Sem título")
    source = str(getattr(lot, "source", None) or "-")
    make = str(getattr(lot, "make", None) or "-")
    item_type = str(getattr(lot, "item_type", None) or "-")
    status = str(getattr(lot, "status", None) or "-")
    year = getattr(lot, "year", None)
    mileage = _fmt_int_br(getattr(lot, "mileage_km", None))
    initial_bid = _fmt_money_br(getattr(lot, "initial_bid", None))
    current_bid = _fmt_money_br(getattr(lot, "current_bid", None))
    total_bids = getattr(lot, "total_bids", None)
    city = str(getattr(lot, "city", None) or "").strip()
    state = str(getattr(lot, "state", None) or "").strip()
    location = " / ".join([x for x in [city, state] if x]) if (city or state) else None
    auction_start_at = _fmt_dt_utc(getattr(lot, "auction_start_at", None))
    auction_end_at = _fmt_dt_utc(getattr(lot, "auction_end_at", None))
    url = str(getattr(lot, "url", None) or "-")
    extras = getattr(lot, "extras", None) or {}
    plate_final = extras.get("plate_final") if isinstance(extras, dict) else None
    skip_reason = extras.get("skip_reason") if isinstance(extras, dict) else None

    lines = [
        f"⚠️ Leilão — {source}",
        title,
        f"{make} | {item_type} | {status}",
    ]
    if year:
        lines.append(f"Ano: {year}")
    if mileage:
        lines.append(f"KM: {mileage}")
    if initial_bid:
        lines.append(f"Lance inicial: {initial_bid}")
    if current_bid:
        lines.append(f"Lance atual: {current_bid}")
    if total_bids is not None:
        lines.append(f"Lances: {total_bids}")
    if location:
        lines.append(f"Local: {location}")
    if auction_start_at:
        lines.append(f"Início: {auction_start_at}")
    if auction_end_at:
        lines.append(f"Encerra: {auction_end_at}")
    if plate_final:
        lines.append(f"Placa final: {plate_final}")
    if status == "invalid" or skip_reason == "generic_page":
        lines.append("⚠️ registro histórico inválido/generic_page")
    lines.append(f"Link: {url}")
    return "\n".join(lines)


def render_admin_auctions_summary(stats: dict, latest_lots: list) -> str:
    total = int(stats.get("total_lots") or 0)
    by_source = stats.get("by_source") or {}
    by_status = stats.get("by_status") or {}
    by_item_type = stats.get("by_item_type") or {}

    lines = ["⚠️ Admin Leilões", f"Total de lotes: {total}", ""]
    lines.append("Por source:")
    if by_source:
        for key, value in sorted(by_source.items(), key=lambda kv: (-int(kv[1]), str(kv[0]))):
            lines.append(f"- {key}: {value}")
    else:
        lines.append("- (vazio)")
    lines.append("")
    lines.append("Por status:")
    if by_status:
        for key, value in sorted(by_status.items(), key=lambda kv: (-int(kv[1]), str(kv[0]))):
            lines.append(f"- {key or 'unknown'}: {value}")
    else:
        lines.append("- (vazio)")
    lines.append("")
    lines.append("Por tipo:")
    if by_item_type:
        for key, value in sorted(by_item_type.items(), key=lambda kv: (-int(kv[1]), str(kv[0]))):
            lines.append(f"- {key or 'other'}: {value}")
    else:
        lines.append("- (vazio)")
    lines.append("")
    lines.append("Últimos lotes:")
    if latest_lots:
        for lot in latest_lots:
            updated_at = _fmt_dt_utc(getattr(lot, "updated_at", None)) or "-"
            lines.append(f"- {getattr(lot, 'source', '-')}/{getattr(lot, 'external_id', '-')}: {getattr(lot, 'title', 'Sem título')} ({updated_at})")
    else:
        lines.append("- Nenhum lote persistido ainda.")
    return "\n".join(lines)


def render_upgrade_text(has_payment_links: bool) -> str:
    text = (
        "🚀 Garagem Alvo Premium\n\n"
        "Para quem já perdeu o carro certo porque alguém chegou primeiro.\n\n"
        "No Free, você testa o monitoramento.\n"
        "No Premium, você aumenta o radar.\n\n"
        "O que muda na prática:\n"
        "• Mais buscas salvas para monitorar vários modelos/configurações ao mesmo tempo.\n"
        "• Mais alertas por dia por busca, reduzindo a chance de perder oportunidade boa por limite.\n"
        "• Mais anúncios rastreados para acompanhar preço e status de carros específicos.\n"
        "• Prioridade nas próximas melhorias do Garagem Alvo.\n\n"
        "Planos de lançamento:\n"
        "Mensal — R$ 5,99/mês\n"
        "Anual — R$ 59,99/ano\n"
        "Equivale a R$ 4,99/mês.\n\n"
        "Depois de pagar, envie o comprovante aqui no Telegram.\n"
        "A ativação é manual."
    )
    if has_payment_links:
        text += "\n\nEscolha uma opção abaixo para continuar."
    else:
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


def build_url_button_keyboard(label: str, url: str):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    safe_url = str(url or "").strip()
    if not safe_url:
        return None
    safe_label = str(label or "").strip() or "🔗 Abrir link"
    return InlineKeyboardMarkup([[InlineKeyboardButton(safe_label, url=safe_url)]])


def build_auction_alert_keyboard(url: str):
    return build_url_button_keyboard("🔗 Ver leilão", url)


def render_admin_auction_quality_report(report: dict) -> str:
    def _fmt_dt(value):
        if not value:
            return "-"
        return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = ["⚠️ Admin Leilões — qualidade", ""]
    sources = report.get("sources") or []
    if not sources:
        lines.append("Nenhuma source encontrada.")
        return "\n".join(lines)

    for idx, item in enumerate(sources):
        total = int(item.get("total_lots", 0) or 0)
        lines.extend([
            f"{item.get('source', '-')}",
            f"Score: {int(item.get('quality_score', 0) or 0)}/100 — {item.get('quality_label', 'sem dados')}",
            f"Lotes: {total}",
            f"Atualizados 24h: {int(item.get('updated_last_24h', 0) or 0)}",
            f"Com lance atual: {int(item.get('with_current_bid_count', 0) or 0)}/{total}",
            f"Com lance inicial: {int(item.get('with_initial_bid_count', 0) or 0)}/{total}",
            f"Com ano: {int(item.get('with_year_count', 0) or 0)}/{total}",
            f"Com início: {int(item.get('with_auction_start_at_count', 0) or 0)}/{total}",
            f"Com encerramento: {int(item.get('with_auction_end_at_count', 0) or 0)}/{total}",
            f"Com cidade/UF: {int(item.get('with_city_state_count', 0) or 0)}/{total}",
            f"Com URL: {int(item.get('with_url_count', 0) or 0)}/{total}",
            f"Com imagem: {int(item.get('with_image_count', 0) or 0)}/{total}",
            f"Open/live: {int(item.get('open_or_live_count', 0) or 0)}",
            f"Car lots: {int(item.get('car_lots', 0) or 0)}",
            f"User allowed lots: {int(item.get('user_allowed_lots', 0) or 0)}",
            f"Qualidade dados car: {'sim' if item.get('data_quality_ready_car') else 'não'}",
            f"Pronta user-facing car: {'sim' if item.get('user_facing_ready_car') else 'não'}",
            f"Motivo user-facing: {item.get('user_facing_ready_reason') or '-'}",
            f"Janela piloto car: {int(item.get('car_pilot_window_hours', report.get('car_pilot_window_hours', 48)) or 48)}h",
            f"Último update: {_fmt_dt(item.get('latest_updated_at'))}",
            f"Aviso: {item.get('stale_warning') or '-'}",
        ])
        critical_warnings = item.get("critical_warnings") or []
        if critical_warnings:
            lines.append(f"Warning crítico: {'; '.join(str(x) for x in critical_warnings)}")
        types = item.get("item_type_counts") or {}
        lines.extend([
            "Tipos:",
            f"- car: {int(types.get('car', 0) or 0)}",
            f"- motorcycle: {int(types.get('motorcycle', 0) or 0)}",
            f"- truck: {int(types.get('truck', 0) or 0)}",
            f"- real_estate: {int(types.get('real_estate', 0) or 0)}",
            f"- other: {int(types.get('other', 0) or 0)}",
            f"- missing: {int(types.get(None, 0) or 0)}",
        ])
        if idx < len(sources) - 1:
            lines.append("")

    return "\n".join(lines).strip()


def render_admin_auction_source_history(report: dict) -> str:
    source = str(report.get("source") or "-")
    current_score = report.get("current_score")
    cycles = report.get("cycles") or []
    lines = [f"⚠️ Admin Leilões — monitor {source}", f"Score atual: {current_score if current_score is not None else '-'}", ""]
    if not cycles:
        lines.append("Sem histórico de ciclos para esta source.")
        return "\n".join(lines).strip()
    for item in cycles:
        at = item.get("at")
        at_s = at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if at else "-"
        lines.extend(
            [
                f"{at_s}",
                f"encontrados={int(item.get('found', 0) or 0)} atualizados={int(item.get('updated', 0) or 0)} erros={int(item.get('errors', 0) or 0)}",
                f"score={item.get('score') if item.get('score') is not None else '-'} carros={int(item.get('car_lots', 0) or 0)}",
                f"lance_atual={int(item.get('with_current_bid_count', 0) or 0)} início={int(item.get('with_auction_start_at_count', 0) or 0)} encerramento={int(item.get('with_auction_end_at_count', 0) or 0)}",
                "",
            ]
        )
    return "\n".join(lines).strip()



def _render_auction_alert_body(match) -> str:
    def _has_value(value) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        return True

    source_raw = str(getattr(match, "source", "") or "").strip()
    source = render_auction_source_label(source_raw)
    title = str(getattr(match, "title", "") or "Sem título")
    query = str(getattr(match, "wishlist_query", "") or "").strip()
    year = getattr(match, "year", None)
    mileage = _fmt_int_br(getattr(match, "mileage_km", None))
    current_bid = _fmt_money_br(getattr(match, "current_bid", None))
    initial_bid = _fmt_money_br(getattr(match, "initial_bid", None))
    total_bids = getattr(match, "total_bids", None)
    city = str(getattr(match, "city", "") or "").strip()
    state = str(getattr(match, "state", "") or "").strip()
    raw_location = str(getattr(match, "location", "") or "").strip()
    location = "/".join([x for x in [city, state] if x]) if (city or state) else (raw_location or None)
    raw_ends_at = getattr(match, "auction_end_at", None)
    ends_at = _fmt_dt_utc(raw_ends_at) if isinstance(raw_ends_at, datetime) else (str(raw_ends_at).strip() if _has_value(raw_ends_at) else None)
    url = str(getattr(match, "url", "") or "").strip()
    lines = [
        "⚠️ Oportunidade em leilão encontrada",
        "",
        title,
    ]
    lines.extend(["", "⚠️ Lance não é preço final. Verifique edital e taxas."])

    if query:
        lines.append("")
        lines.append(f"Busca: {query}")
    lines.extend([f"Fonte: {source}"])
    lines.append("")
    if current_bid:
        lines.append(f"Lance atual: {current_bid}")
    if initial_bid:
        lines.append(f"Lance inicial: {initial_bid}")
    if _has_value(total_bids):
        lines.append(f"Lances: {total_bids}")
    if ends_at:
        lines.append(f"Encerra: {ends_at}")
    if location:
        lines.append(f"Local: {location}")
    if _has_value(year) or mileage:
        if _has_value(year) and mileage:
            lines.append(f"Ano/KM: {year}/{mileage}")
        elif _has_value(year):
            lines.append(f"Ano: {year}")
        else:
            lines.append(f"KM: {mileage}")
    lines.extend(["", "Antes de participar, confira comissão, documentação e vistoria."])
    return "\n".join(lines).strip()


def render_auction_source_label(source_key: str) -> str:
    source = str(source_key or "").strip()
    labels = {
        "vip_auctions": "VIP Leilões",
        "mega_auctions": "Mega Leilões",
        "win_auctions": "Win Leilões",
        "sodre_auctions": "Sodré Santoro",
        "superbid_auctions": "Superbid",
        "copart_auctions": "Copart",
    }
    if source in labels:
        return labels[source]
    source_def = get_auction_source_definition(source)
    if source_def and source_def.label:
        return source_def.label
    return source or "-"


def render_auction_alert(match) -> str:
    return _render_auction_alert_body(match)


def render_auction_alert_preview(match) -> str:
    note = ""
    if getattr(match, "current_bid", None) is None and getattr(match, "initial_bid", None) is None:
        note = "⚠️ Sem lance capturado — não elegível para envio automático/manual padrão.\n\n"
    return "🧪 Preview — alerta de leilão\n\n" + note + _render_auction_alert_body(match)
