import logging

from telegram import BotCommand, BotCommandScopeChat, BotCommandScopeDefault
from telegram.error import BadRequest

from app.core.settings import settings
logger = logging.getLogger(__name__)


def _parse_admin_chat_ids() -> set[int]:
    raw = (settings.autohunter_admin_chat_ids or settings.autohunter_admins or "")
    return {int(x.strip()) for x in str(raw).split(",") if x.strip().lstrip("-").isdigit()}


# Comandos públicos enxutos no menu do Telegram (autopreenchimento)
PUBLIC_COMMANDS = [
    BotCommand("start", "Iniciar / registrar"),
    BotCommand("menu", "Menu guiado de ações"),
    BotCommand("help", "Ver ajuda"),
    BotCommand("cancelar", "Cancelar fluxo guiado"),
]

# Compat: testes/código legado ainda referenciam COMMANDS
COMMANDS = PUBLIC_COMMANDS


ADMIN_COMMANDS = [
    BotCommand("admin", "Admin (sources, etc.)"),
    BotCommand("debug", "Debug (admin)"),
    BotCommand("setplan", "Setar plano (admin)"),
    BotCommand("setlimit", "Setar limite de notificações (admin)"),
]


ADVANCED_USER_COMMANDS = [
    BotCommand("status", "Status e limites"),
    BotCommand("version", "Versão do bot"),
    BotCommand("buscar", "Busca manual (não salva)"),
    BotCommand("wishlist", "Listar buscas (legado)"),
    BotCommand("wishlist_add", "Criar busca (assistente legado)"),
    BotCommand("wishlist_help", "Ajuda avançada de buscas"),
    BotCommand("wishlist_remove", "Remover busca (legado)"),
    BotCommand("wishlist_clear", "Remover todas as wishlists"),
    BotCommand("wishlist_track_add", "Rastrear anúncio da busca"),
    BotCommand("wishlist_track_list", "Listar rastreados da wishlist"),
    BotCommand("wishlist_track_remove", "Remover rastreado da wishlist"),
    BotCommand("wishlist_track_alert_on", "Ativar alerta de queda por slot"),
    BotCommand("wishlist_track_alert_off", "Desativar alerta de queda por slot"),
    BotCommand("alertas", "Info / painel simples"),
    BotCommand("me", "Seu chat_id"),
    BotCommand("plan", "Seu plano"),
    BotCommand("upgrade", "Upgrade de plano"),
]


ADMIN_SCOPED_COMMANDS = [*PUBLIC_COMMANDS, *ADMIN_COMMANDS]


async def setup_bot_commands(bot):
    # escopo default: aplica para todos os usuários
    await bot.set_my_commands(PUBLIC_COMMANDS, scope=BotCommandScopeDefault())
    for chat_id in _parse_admin_chat_ids():
        try:
            await bot.set_my_commands(ADMIN_SCOPED_COMMANDS, scope=BotCommandScopeChat(chat_id=chat_id))
        except BadRequest as exc:
            if "chat not found" in str(exc).lower():
                logger.warning(
                    "skipping admin scoped Telegram commands for chat_id=%s: chat not found; "
                    "confirm AUTOHUNTER_ADMIN_CHAT_IDS and make sure the admin has started the bot",
                    chat_id,
                )
                continue
            logger.warning("failed to register admin scoped Telegram commands for chat_id=%s", chat_id, exc_info=True)
        except Exception:
            logger.warning("failed to register admin scoped Telegram commands for chat_id=%s", chat_id, exc_info=True)
