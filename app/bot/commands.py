from telegram import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

from app.core.settings import settings


def _parse_admin_chat_ids() -> set[int]:
    raw = (settings.autohunter_admin_chat_ids or settings.autohunter_admins or "")
    return {int(x.strip()) for x in str(raw).split(",") if x.strip().lstrip("-").isdigit()}


# Comandos públicos enxutos no menu do Telegram (autopreenchimento)
COMMANDS = [
    BotCommand("menu", "Menu guiado de ações"),
    BotCommand("help", "Ver ajuda"),
    BotCommand("cancelar", "Cancelar fluxo guiado"),
]


ADMIN_COMMANDS = [
    BotCommand("admin", "Admin (sources, etc.)"),
    BotCommand("debug", "Debug (admin)"),
    BotCommand("setplan", "Setar plano (admin)"),
    BotCommand("setlimit", "Setar limite de notificações (admin)"),
]


ADVANCED_USER_COMMANDS = [
    BotCommand("start", "Iniciar / registrar"),
    BotCommand("status", "Status e limites"),
    BotCommand("version", "Versão do bot"),
    BotCommand("buscar", "Busca manual (não salva)"),
    BotCommand("wishlist", "Listar wishlists"),
    BotCommand("wishlist_add", "Criar wishlist (assistente)"),
    BotCommand("wishlist_help", "Ajuda de wishlists (filtros e exemplos)"),
    BotCommand("wishlist_remove", "Remover wishlist"),
    BotCommand("wishlist_clear", "Remover todas as wishlists"),
    BotCommand("wishlist_track_add", "Rastrear anúncio da wishlist"),
    BotCommand("wishlist_track_list", "Listar rastreados da wishlist"),
    BotCommand("wishlist_track_remove", "Remover rastreado da wishlist"),
    BotCommand("wishlist_track_alert_on", "Ativar alerta de queda por slot"),
    BotCommand("wishlist_track_alert_off", "Desativar alerta de queda por slot"),
    BotCommand("alertas", "Info / painel simples"),
    BotCommand("me", "Seu chat_id"),
    BotCommand("plan", "Seu plano"),
    BotCommand("upgrade", "Upgrade de plano"),
]


async def setup_bot_commands(bot):
    # escopo default: aplica para todos os usuários
    await bot.set_my_commands(COMMANDS, scope=BotCommandScopeDefault())
    for chat_id in _parse_admin_chat_ids():
        await bot.set_my_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=chat_id))
