from telegram import BotCommand, BotCommandScopeDefault


# Comandos que aparecem no menu do Telegram (autopreenchimento)
COMMANDS = [
    BotCommand("start", "Iniciar / registrar"),
    BotCommand("help", "Ver comandos e exemplos"),
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

    BotCommand("alertas", "Info / painel simples"),
    BotCommand("me", "Seu chat_id"),
    BotCommand("debug", "Debug (admin)"),

    BotCommand("admin", "Admin (sources, etc.)"),

    BotCommand("plan", "Seu plano"),
    BotCommand("upgrade", "Upgrade de plano"),
    BotCommand("setplan", "Setar plano (admin)"),
    BotCommand("setlimit", "Setar limite de notificações (admin)"),
]


async def setup_bot_commands(bot):
    # escopo default: aplica para todos
    await bot.set_my_commands(COMMANDS, scope=BotCommandScopeDefault())
