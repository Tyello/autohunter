from telegram import Update
from telegram.ext import ContextTypes

from app.bot.utils import reply_text
from app.db.session import SessionLocal
from app.services.users_service import get_or_create_user_by_chat
from app.services.wishlists_service import list_wishlists, get_user_plan_snapshot


def _wishlist_help_text() -> str:
    return (
        "🧰 Wishlist — ajuda rápida\n\n"
        "Criar (assistente):\n"
        "• /wishlist_add\n"
        "  Depois digite, por exemplo:\n"
        "  - audi a6 entre 2014 e 2020\n"
        "  - audi a6 a partir de 2014\n"
        "  - audi a6 até 2020\n"
        "  - audi a6 entre 200k e 300k\n"
        "  - audi a6 até R$ 120.000\n\n"
        "Fluxo oficial recomendado:\n"
        "• /wishlist_add (assistente)\n\n"
        "Compatibilidade (modo antigo):\n"
        "• /wishlist add audi a6\n\n"
        "Diretivas embutidas no texto (criam filtros automáticos):\n"
        "• Ano: entre 2014 e 2020 | 2014-2020 | a partir de 2014 | até 2020 | ano>=2014 | ano<=2020\n"
        "• Preço (BRL): entre 200k e 300k | 200k-300k | a partir de 80k | até 120k | preço>=80k | valor<=120k\n"
        "  (k=mil, m=milhão; também aceita R$ 80.000)\n\n"
        "Equivalente em filtros manuais:\n"
        "• /wishlist_filter_add <n> year gte 2014\n"
        "• /wishlist_filter_add <n> year lte 2020\n"
        "• /wishlist_filter_add <n> price gte 200000\n"
        "• /wishlist_filter_add <n> price lte 300000\n\n"
        "Outros filtros úteis:\n"
        "• /wishlist_filter_add <n> price lte 90000\n"
        "• /wishlist_filter_add <n> km <= 80000\n"
        "• /wishlist_filter_add <n> km entre 30000 90000\n"
        "• /wishlist_filter_add <n> source eq icarros\n"
        "• /wishlist_filter_add <n> color eq prata\n"
        "• /wishlist_filter_add <n> city eq sao paulo\n"
        "• /wishlist_filter_add <n> state eq SP\n"
        "• /wishlist_filter_add <n> vendedor = particular\n"
        "• /wishlist_filter_add <n> vendedor apenas loja\n"
        "• /wishlist_filter_add <n> vendedor excluir revenda\n\n"
        "• /wishlist_filter_add <n> carroceria = suv\n"
        "• /wishlist_filter_add <n> carroceria excluir pickup\n\n"
        "Ver/remover filtros:\n"
        "• /wishlist_filter_list <n>\n"
        "• /wishlist_filter_remove <n> <k>\n\n"
        "Rastrear até 3 anúncios por wishlist:\n"
        "• /wishlist_track_add <n> <url|external_id>\n"
        "• /wishlist_track_list <n>\n"
        "• /wishlist_track_remove <n> <slot>\n\n"
        "Dica: /wishlist mostra o número <n>.\n"
        "Obs: filtros de preço só dão match quando a fonte extrai preço (se vier None, não entra em range)."
    )




async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
        w = list_wishlists(db, user.id)

    await reply_text(
        update,
        "👋 Bem-vindo ao AutoHunter!\n\n"
        f"Você tem {len(w)} wishlist(s) ativa(s).\n"
        "Use /wishlist para listar, /wishlist_add para criar e /wishlist_help para ajuda."
    )

async def cmd_wishlist_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reply_text(update, _wishlist_help_text())


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reply_text(
        update,
        "📌 Comandos do AutoHunter\n\n"
        "Wishlist:\n"
        "• /wishlist — listar\n"
        "• /wishlist_add — criar (assistente)\n"
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
        "Campos: price | year | mileage_km | source | color | city | state | seller_type | body_type (aliases body_type: carroceria, tipo_carroceria, categoria, estilo)\n"
        "Ops price/year/mileage_km: lt lte gt gte eq neq between (alias: entre)\n"
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
        "Dica (atalho no /wishlist_add):\n"
        "• \"daihatsu cuore até 2005\" (cria filtro year lte 2005 automaticamente)\n\n"
        "Busca manual:\n"
        "• /buscar civic 2019 até 90000 sp\n\n"
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


async def cmd_version(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await reply_text(update, "🤖 AutoHunter (bot) — appv4")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with SessionLocal() as db:
        user = get_or_create_user_by_chat(db, update.effective_chat.id, update.effective_user.username)
        w = list_wishlists(db, user.id)
        snap = get_user_plan_snapshot(db, user.id)

    max_w = snap.get("max_wishlists")
    dal = snap.get("daily_alert_limit")
    plan_code = snap.get("plan_code") or "free"

    dal_txt = str(dal) if dal is not None else "—"

    await reply_text(
        update,
        "📊 Status\n\n"
        f"Plano: {plan_code}\n"
        f"Wishlists: {len(w)}/{max_w}\n"
        f"Alertas/dia: {dal_txt}\n"
        "Monitoramento: fontes via scheduler\n\n"
        "Use /wishlist para ver suas buscas monitoradas."
    )
