"""Handlers para o fluxo 'buscar agora': termo → facetas → refinamento → top-10.

Implementa a Etapa 1 da spec 018-buscar-agora-bot-flow:
- Usuário digita termo com /buscar_agora
- Sistema mostra facetas calculadas via compute_facet_counts
- Usuário refina clicando em facetas/buckets
- Sistema re-renderiza facetas com filtros acumulados
- Usuário vê até 10 anúncios

Passo 4 (reentry/edição de filtros) fica para Etapa 2.
"""

import asyncio
import logging
from decimal import Decimal
from types import SimpleNamespace

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters
from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.car_listing import CarListing
from app.services.facet_search_service import (
    compute_facet_counts, FacetCount, _year_bucket_expr, _price_bucket_expr, _mileage_bucket_expr
)
from app.services.users_service import get_or_create_user_by_chat
from app.scoring.score_v2 import score_ad
from app.notifications.telegram_formatter import format_ad_message
from app.bot.utils import reply_text
from app.bot.handlers_core import (
    MENU_CREATE_WISHLIST_QUERY, menu_create_wishlist_conversation,
    build_draft_filter_groups, _show_create_wishlist_summary_screen
)
from app.services.wishlists_service import parse_wishlist_query_with_implicit_filters

logger = logging.getLogger(__name__)

# Estados da conversação
BUSCAR_AGORA_TERM = 2001
BUSCAR_AGORA_FACETS = 2002

# Handlers reutilizados do fluxo de criação de wishlist
_wishlist_query_handlers = menu_create_wishlist_conversation().states[MENU_CREATE_WISHLIST_QUERY]


def _bucket_to_condition(facet: str, bucket: str | None) -> list:
    """Reconstrói condição SQLAlchemy a partir de faceta e bucket.

    Categórico (state, city, color, body_type, doors, make, model) → igualdade exata
    Numérico bucketizado (year, price, mileage_km) → intervalo do bucket usando
    mesmos limiares de _year_bucket_expr, _price_bucket_expr, _mileage_bucket_expr.

    Args:
        facet: nome da faceta (ex. "year", "price", "state")
        bucket: valor do bucket selecionado (ex. "2015-2019", "SP", "< 20.000")

    Returns:
        Lista de condições SQLAlchemy (vazia se faceta/bucket inválido)
    """
    if not bucket:
        return []

    # Facetas categóricas → igualdade exata
    if facet == "state":
        return [CarListing.state == bucket]
    elif facet == "city":
        return [CarListing.city == bucket]
    elif facet == "color":
        return [CarListing.color == bucket]
    elif facet == "body_type":
        return [CarListing.body_type == bucket]
    elif facet == "doors":
        try:
            doors_val = int(bucket)
            return [CarListing.doors == doors_val]
        except (ValueError, TypeError):
            return []
    elif facet == "make":
        return [CarListing.make == bucket]
    elif facet == "model":
        return [CarListing.model == bucket]

    # Facetas numérico-bucketizadas → intervalo
    elif facet == "year":
        if bucket == "< 2010":
            return [CarListing.year < 2010]
        elif bucket == "2010-2014":
            return [CarListing.year.between(2010, 2014)]
        elif bucket == "2015-2019":
            return [CarListing.year.between(2015, 2019)]
        elif bucket == "2020-2024":
            return [CarListing.year.between(2020, 2024)]
        elif bucket == "2025+":
            return [CarListing.year >= 2025]

    elif facet == "price":
        # Normaliza vírgulas/pontos para parsing
        bucket_clean = bucket.replace(".", "").replace(",", "")
        try:
            if bucket == "< 20.000":
                return [CarListing.price < 20000]
            elif bucket == "20.000-39.999":
                return [and_(CarListing.price >= 20000, CarListing.price < 40000)]
            elif bucket == "40.000-59.999":
                return [and_(CarListing.price >= 40000, CarListing.price < 60000)]
            elif bucket == "60.000-79.999":
                return [and_(CarListing.price >= 60000, CarListing.price < 80000)]
            elif bucket == "80.000-99.999":
                return [and_(CarListing.price >= 80000, CarListing.price < 100000)]
            elif bucket == "100.000-149.999":
                return [and_(CarListing.price >= 100000, CarListing.price < 150000)]
            elif bucket == "150.000+":
                return [CarListing.price >= 150000]
        except (ValueError, TypeError):
            return []

    elif facet == "mileage_km":
        bucket_clean = bucket.replace(".", "").replace(",", "").replace(" km", "")
        try:
            if bucket == "< 20.000 km":
                return [CarListing.mileage_km < 20000]
            elif bucket == "20.000-49.999 km":
                return [and_(CarListing.mileage_km >= 20000, CarListing.mileage_km < 50000)]
            elif bucket == "50.000-99.999 km":
                return [and_(CarListing.mileage_km >= 50000, CarListing.mileage_km < 100000)]
            elif bucket == "100.000-149.999 km":
                return [and_(CarListing.mileage_km >= 100000, CarListing.mileage_km < 150000)]
            elif bucket == "150.000+ km":
                return [CarListing.mileage_km >= 150000]
        except (ValueError, TypeError):
            return []

    return []


def _bucket_to_filter_descriptors(facet: str, bucket: str) -> list:
    """Reconstrói descritores de filtro (estrutura normalizada) a partir de faceta e bucket.

    Espelha _bucket_to_condition mas retorna SimpleNamespace(field=..., operator=..., value=...)
    em vez de condições SQLAlchemy. Todos os valores são strings.

    Categórico (state, city, color, body_type, doors, make, model) → operador "eq"
    Numérico bucketizado (year, price, mileage_km) → operadores "gte"/"lte"/"lt"

    Args:
        facet: nome da faceta (ex. "year", "price", "state")
        bucket: valor do bucket selecionado (ex. "2015-2019", "SP", "< 20.000")

    Returns:
        Lista de SimpleNamespace com field, operator, value (todos como str)
    """
    if not bucket:
        return []

    # Facetas categóricas → igualdade exata (operador "eq")
    if facet == "state":
        return [SimpleNamespace(field="state", operator="eq", value=bucket)]
    elif facet == "city":
        return [SimpleNamespace(field="city", operator="eq", value=bucket)]
    elif facet == "color":
        return [SimpleNamespace(field="color", operator="eq", value=bucket)]
    elif facet == "body_type":
        return [SimpleNamespace(field="body_type", operator="eq", value=bucket)]
    elif facet == "doors":
        return [SimpleNamespace(field="doors", operator="eq", value=bucket)]
    elif facet == "make":
        return [SimpleNamespace(field="make", operator="eq", value=bucket)]
    elif facet == "model":
        return [SimpleNamespace(field="model", operator="eq", value=bucket)]

    # Facetas numérico-bucketizadas → intervalos (operadores "lt", "gte", "lte")
    elif facet == "year":
        if bucket == "< 2010":
            return [SimpleNamespace(field="year", operator="lt", value="2010")]
        elif bucket == "2010-2014":
            return [
                SimpleNamespace(field="year", operator="gte", value="2010"),
                SimpleNamespace(field="year", operator="lte", value="2014"),
            ]
        elif bucket == "2015-2019":
            return [
                SimpleNamespace(field="year", operator="gte", value="2015"),
                SimpleNamespace(field="year", operator="lte", value="2019"),
            ]
        elif bucket == "2020-2024":
            return [
                SimpleNamespace(field="year", operator="gte", value="2020"),
                SimpleNamespace(field="year", operator="lte", value="2024"),
            ]
        elif bucket == "2025+":
            return [SimpleNamespace(field="year", operator="gte", value="2025")]

    elif facet == "price":
        try:
            if bucket == "< 20.000":
                return [SimpleNamespace(field="price", operator="lt", value="20000")]
            elif bucket == "20.000-39.999":
                return [
                    SimpleNamespace(field="price", operator="gte", value="20000"),
                    SimpleNamespace(field="price", operator="lt", value="40000"),
                ]
            elif bucket == "40.000-59.999":
                return [
                    SimpleNamespace(field="price", operator="gte", value="40000"),
                    SimpleNamespace(field="price", operator="lt", value="60000"),
                ]
            elif bucket == "60.000-79.999":
                return [
                    SimpleNamespace(field="price", operator="gte", value="60000"),
                    SimpleNamespace(field="price", operator="lt", value="80000"),
                ]
            elif bucket == "80.000-99.999":
                return [
                    SimpleNamespace(field="price", operator="gte", value="80000"),
                    SimpleNamespace(field="price", operator="lt", value="100000"),
                ]
            elif bucket == "100.000-149.999":
                return [
                    SimpleNamespace(field="price", operator="gte", value="100000"),
                    SimpleNamespace(field="price", operator="lt", value="150000"),
                ]
            elif bucket == "150.000+":
                return [SimpleNamespace(field="price", operator="gte", value="150000")]
        except (ValueError, TypeError):
            return []

    elif facet == "mileage_km":
        try:
            if bucket == "< 20.000 km":
                return [SimpleNamespace(field="mileage_km", operator="lt", value="20000")]
            elif bucket == "20.000-49.999 km":
                return [
                    SimpleNamespace(field="mileage_km", operator="gte", value="20000"),
                    SimpleNamespace(field="mileage_km", operator="lt", value="50000"),
                ]
            elif bucket == "50.000-99.999 km":
                return [
                    SimpleNamespace(field="mileage_km", operator="gte", value="50000"),
                    SimpleNamespace(field="mileage_km", operator="lt", value="100000"),
                ]
            elif bucket == "100.000-149.999 km":
                return [
                    SimpleNamespace(field="mileage_km", operator="gte", value="100000"),
                    SimpleNamespace(field="mileage_km", operator="lt", value="150000"),
                ]
            elif bucket == "150.000+ km":
                return [SimpleNamespace(field="mileage_km", operator="gte", value="150000")]
        except (ValueError, TypeError):
            return []

    return []


def _render_facets_keyboard(facet_counts: list[FacetCount]) -> InlineKeyboardMarkup:
    """Renderiza teclado inline com facetas.

    Agrupa por faceta, mostra top-20 buckets por faceta.

    Args:
        facet_counts: lista de FacetCount da busca

    Returns:
        InlineKeyboardMarkup com facetas e botões de ação
    """
    # Agrupa por faceta
    by_facet = {}
    total_count = 0
    for fc in facet_counts:
        if fc.facet == "__total__":
            total_count = fc.count
            continue
        if fc.facet not in by_facet:
            by_facet[fc.facet] = []
        by_facet[fc.facet].append(fc)

    # Ordem de exibição das facetas
    facet_order = ["state", "city", "make", "model", "color", "body_type", "doors", "year", "price", "mileage_km"]

    buttons = []

    # Header com total de resultados
    if total_count > 0:
        buttons.append([InlineKeyboardButton(f"📊 Total: {total_count} anúncios", callback_data="NOOP")])

    # Cada faceta em seu próprio grupo
    for facet in facet_order:
        if facet not in by_facet or not by_facet[facet]:
            continue

        # Header da faceta
        facet_label = {
            "state": "🗺️ Estado",
            "city": "🏙️ Cidade",
            "make": "🚗 Marca",
            "model": "📍 Modelo",
            "color": "🎨 Cor",
            "body_type": "🔷 Carroceria",
            "doors": "🚪 Portas",
            "year": "📅 Ano",
            "price": "💰 Preço",
            "mileage_km": "⛽ Km",
        }.get(facet, facet)

        buttons.append([InlineKeyboardButton(f"━━━ {facet_label} ━━━", callback_data="NOOP")])

        # Buckets (máx 5 por linha, máx 20 buckets por faceta)
        row = []
        for i, fc in enumerate(by_facet[facet][:20]):
            if fc.bucket is None:
                continue
            btn_text = f"{fc.bucket} ({fc.count})"
            callback_data = f"BUSCAR_AGORA:FACET:{facet}:{fc.bucket}"
            row.append(InlineKeyboardButton(btn_text, callback_data=callback_data))

            if len(row) == 5 or i == len(by_facet[facet]) - 1:
                buttons.append(row)
                row = []

    # Botões de ação no rodapé
    buttons.append([
        InlineKeyboardButton("🔝 Ver os 10 primeiros", callback_data="BUSCAR_AGORA:TOP10"),
        InlineKeyboardButton("❌ Cancelar", callback_data="BUSCAR_AGORA:CANCEL"),
    ])

    return InlineKeyboardMarkup(buttons)


async def cmd_buscar_agora(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia o fluxo de busca rápida com refinamento por facetas."""
    await reply_text(
        update,
        "🔍 Buscar agora com refinamento\n\n"
        "O que você procura?\n\n"
        "Exemplos:\n"
        "- civic si até 120000 sp\n"
        "- golf gti manual\n"
        "- audi a5 2018"
    )
    return BUSCAR_AGORA_TERM


async def buscar_agora_on_term(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa termo digitado, calcula facetas e renderiza."""
    term = (update.message.text or "").strip()
    if not term:
        await reply_text(update, "Me diga o que você quer buscar. Exemplo: civic si até 120000 sp")
        return BUSCAR_AGORA_TERM

    # Salva termo e inicializa filtros extras
    context.user_data["buscar_agora_term"] = term
    context.user_data["buscar_agora_extra_filters"] = []
    context.user_data["buscar_agora_extra_filters_struct"] = []

    # Calcula facetas em thread separada
    def _compute_facets():
        with SessionLocal() as db:
            try:
                facet_counts = compute_facet_counts(db, term, extra_conditions=None)
                return facet_counts, None
            except Exception as e:
                logger.exception(f"compute_facet_counts failed for term '{term}'", exc_info=True)
                return None, str(e)

    facet_counts, err = await asyncio.to_thread(_compute_facets)

    if err or facet_counts is None:
        await reply_text(update, "Não consegui calcular as facetas agora. Tente novamente.")
        return BUSCAR_AGORA_TERM

    # Se nenhum resultado, verifica se há filtro válido para oferecer criação de alerta
    total = next((fc.count for fc in facet_counts if fc.facet == "__total__"), 0)
    if total == 0:
        # Tenta parsear o termo para extrair filtros implícitos
        parsed = parse_wishlist_query_with_implicit_filters(term)
        has_valid_filter = bool(parsed.filters)

        if has_valid_filter:
            # Oferece criação de alerta com os filtros extraídos
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔔 Criar alerta para essa busca", callback_data="BUSCAR_AGORA:CREATE_ALERT")],
                [InlineKeyboardButton("❌ Cancelar", callback_data="BUSCAR_AGORA:CANCEL")],
            ])
            await reply_text(
                update,
                "Nenhum anúncio encontrado com esses filtros.\n\n"
                "Quer que eu avise quando aparecer um anúncio assim?",
                reply_markup=kb
            )
            return BUSCAR_AGORA_FACETS
        else:
            # Sem filtro válido, mensagem genérica
            await reply_text(
                update,
                "Nenhum anúncio encontrado para essa busca.\n\n"
                "Tente modificar o termo ou criar uma busca salva para monitorar continuamente."
            )
            return ConversationHandler.END

    # Renderiza facetas
    kb = _render_facets_keyboard(facet_counts)
    await reply_text(
        update,
        f"🔍 Resultados para: {term}\n\n"
        f"Clique em um filtro para refinar. Quando terminar, veja os 10 primeiros anúncios.",
        reply_markup=kb
    )

    return BUSCAR_AGORA_FACETS


async def cb_buscar_agora_facet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa clique em faceta, acumula filtro e re-renderiza."""
    q = update.callback_query
    await q.answer()

    callback_data = q.data or ""
    if not callback_data.startswith("BUSCAR_AGORA:FACET:"):
        return BUSCAR_AGORA_FACETS

    # Parse: BUSCAR_AGORA:FACET:<facet>:<bucket>
    parts = callback_data.split(":", 3)
    if len(parts) < 4:
        return BUSCAR_AGORA_FACETS

    facet = parts[2]
    bucket = parts[3]

    # Reconstrói condição SQLAlchemy
    new_conditions = _bucket_to_condition(facet, bucket)
    if not new_conditions:
        await q.answer("Filtro inválido.", show_alert=True)
        return BUSCAR_AGORA_FACETS

    # Acumula no contexto (ambas as formas: SQLAlchemy e estruturada)
    extra_filters = context.user_data.get("buscar_agora_extra_filters") or []
    extra_filters.extend(new_conditions)
    context.user_data["buscar_agora_extra_filters"] = extra_filters

    # Acumula a forma estruturada para possível criação de alerta
    extra_filters_struct = context.user_data.get("buscar_agora_extra_filters_struct") or []
    extra_filters_struct.extend(_bucket_to_filter_descriptors(facet, bucket))
    context.user_data["buscar_agora_extra_filters_struct"] = extra_filters_struct

    # Re-renderiza facetas com filtros acumulados
    term = context.user_data.get("buscar_agora_term", "")

    def _recompute_facets():
        with SessionLocal() as db:
            try:
                facet_counts = compute_facet_counts(db, term, extra_conditions=extra_filters)
                return facet_counts, None
            except Exception as e:
                logger.exception(f"compute_facet_counts failed on refinement for term '{term}'", exc_info=True)
                return None, str(e)

    facet_counts, err = await asyncio.to_thread(_recompute_facets)

    if err or facet_counts is None:
        await q.answer("Erro ao re-calcular facetas.", show_alert=True)
        return BUSCAR_AGORA_FACETS

    # Verifica se ainda há resultados
    total = next((fc.count for fc in facet_counts if fc.facet == "__total__"), 0)

    if total == 0:
        # Nenhum resultado com esses filtros, oferece alerta
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔔 Criar alerta para essa busca", callback_data="BUSCAR_AGORA:CREATE_ALERT")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="BUSCAR_AGORA:CANCEL")],
        ])
        await q.edit_message_text(
            "Nenhum anúncio encontrado com esses filtros.\n\n"
            "Quer que eu avise quando aparecer um anúncio assim?",
            reply_markup=kb
        )
        return BUSCAR_AGORA_FACETS

    # Mostra quantos filtros estão ativos
    filter_count = len(extra_filters)

    kb = _render_facets_keyboard(facet_counts)
    await q.edit_message_text(
        f"🔍 Resultados para: {term}\n"
        f"🔽 {filter_count} filtro(s) aplicado(s)\n\n"
        f"Clique em outro filtro para refinar mais.",
        reply_markup=kb
    )

    return BUSCAR_AGORA_FACETS


async def cb_buscar_agora_create_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa "Criar alerta" e reentry ao fluxo de criação de wishlist."""
    q = update.callback_query
    await q.answer()

    term = context.user_data.get("buscar_agora_term", "")
    extra_struct = context.user_data.get("buscar_agora_extra_filters_struct") or []

    if not term:
        await q.answer("Sessão expirou.", show_alert=True)
        return ConversationHandler.END

    # Parseia o termo para extrair filtros implícitos
    parsed = parse_wishlist_query_with_implicit_filters(term)

    # Combina filtros do termo com filtros de refinamento acumulados
    all_filters = list(parsed.filters) + extra_struct

    # Monta contexto para o fluxo de criação de wishlist
    context.user_data["menu_create_wishlist_query"] = parsed.cleaned_query
    context.user_data["menu_create_wishlist_draft_filters"] = build_draft_filter_groups(all_filters)
    context.user_data["menu_create_wishlist_include_auctions"] = False

    return await _show_create_wishlist_summary_screen(update, context)


async def cb_buscar_agora_top10(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa "Ver os 10 primeiros": busca anúncios e mostra."""
    q = update.callback_query
    await q.answer()

    term = context.user_data.get("buscar_agora_term", "")
    extra_filters = context.user_data.get("buscar_agora_extra_filters") or []

    if not term:
        await q.answer("Sessão expirou.", show_alert=True)
        return ConversationHandler.END

    # Busca até 10 anúncios
    def _search_listings():
        with SessionLocal() as db:
            try:
                # Reconstrói query com filtros acumulados
                from app.services.facet_search_service import build_search_conditions
                base_conditions, _ = build_search_conditions(term)

                # status != 'inativo' + condições do termo + filtros extras
                all_conditions = [CarListing.status != "inativo"] + base_conditions + extra_filters
                base_predicate = and_(*all_conditions)

                # Busca 10 anúncios, ordena por score (data desc como fallback)
                listings = db.query(CarListing).filter(base_predicate).order_by(
                    CarListing.created_at.desc()
                ).limit(10).all()

                return listings, None
            except Exception as e:
                logger.exception(f"search_listings failed for term '{term}'", exc_info=True)
                return None, str(e)

    listings, err = await asyncio.to_thread(_search_listings)

    if err or listings is None:
        await q.answer("Erro ao buscar anúncios.", show_alert=True)
        return BUSCAR_AGORA_FACETS

    if not listings:
        await q.answer("Nenhum anúncio encontrado com esses filtros.", show_alert=True)
        return BUSCAR_AGORA_FACETS

    # Formata e envia anúncios
    async def _send_listings():
        try:
            chat_id = update.effective_chat.id

            # Header
            await q.edit_message_text(
                f"📋 Mostrando {len(listings)} anúncio(s) para: {term}\n\n"
                f"Clique em 'Abrir anúncio' para ver o anúncio completo."
            )

            for listing in listings:
                try:
                    # Formata anúncio
                    payload = format_ad_message(listing)

                    # Constrói teclado
                    built_rows = []
                    for row in payload.get("inline_keyboard") or []:
                        built = []
                        for btn in row:
                            if btn.get("callback_data"):
                                built.append(InlineKeyboardButton(btn.get("text", "Botão"), callback_data=btn.get("callback_data")))
                            else:
                                built.append(InlineKeyboardButton(btn.get("text", "Abrir anúncio"), url=btn.get("url")))
                        if built:
                            built_rows.append(built)

                    reply_markup = InlineKeyboardMarkup(built_rows) if built_rows else None

                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=payload["text"],
                        reply_markup=reply_markup,
                        disable_web_page_preview=True,
                    )
                except Exception:
                    logger.exception(f"Failed to send listing {listing.id}", exc_info=True)
                    continue
        except Exception:
            logger.exception("_send_listings failed", exc_info=True)

    asyncio.create_task(_send_listings())

    return ConversationHandler.END


async def buscar_agora_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancela o fluxo de busca rápida."""
    # Se chamado via command
    if update.message:
        await reply_text(update, "Busca cancelada.")
    # Se chamado via callback
    elif update.callback_query:
        q = update.callback_query
        await q.answer()
        await q.edit_message_text("Busca cancelada.")

    context.user_data.pop("buscar_agora_term", None)
    context.user_data.pop("buscar_agora_extra_filters", None)
    context.user_data.pop("buscar_agora_extra_filters_struct", None)

    return ConversationHandler.END


def buscar_agora_conversation() -> ConversationHandler:
    """Conversação para busca rápida com refinamento por facetas."""
    return ConversationHandler(
        entry_points=[
            CommandHandler("buscar_agora", cmd_buscar_agora),
        ],
        states={
            BUSCAR_AGORA_TERM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, buscar_agora_on_term),
                MessageHandler(filters.COMMAND, buscar_agora_cancel),
            ],
            BUSCAR_AGORA_FACETS: [
                CallbackQueryHandler(cb_buscar_agora_facet, pattern=r"^BUSCAR_AGORA:FACET:"),
                CallbackQueryHandler(cb_buscar_agora_create_alert, pattern=r"^BUSCAR_AGORA:CREATE_ALERT$"),
                CallbackQueryHandler(cb_buscar_agora_top10, pattern=r"^BUSCAR_AGORA:TOP10$"),
                CallbackQueryHandler(buscar_agora_cancel, pattern=r"^BUSCAR_AGORA:CANCEL$"),
            ],
            MENU_CREATE_WISHLIST_QUERY: _wishlist_query_handlers,
        },
        fallbacks=[
            CommandHandler("cancelar", buscar_agora_cancel),
            CommandHandler("cancel", buscar_agora_cancel),
        ],
        name="buscar_agora",
        persistent=False,
        per_chat=True,
        per_user=True,
        per_message=False,
    )
