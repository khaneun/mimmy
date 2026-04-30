from __future__ import annotations

from telegram.ext import Application, CommandHandler, MessageHandler, filters

from mimmy.config import get_settings
from mimmy.logging import get_logger
from mimmy.telegram_bot import handlers

log = get_logger(__name__)


def build_application() -> Application:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set")

    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(handlers.notify_startup)
        .build()
    )
    app.add_handler(CommandHandler("start", handlers.cmd_start))
    app.add_handler(CommandHandler("help", handlers.cmd_help))
    app.add_handler(CommandHandler("status", handlers.cmd_status))
    app.add_handler(CommandHandler("positions", handlers.cmd_positions))
    app.add_handler(CommandHandler("pause", handlers.cmd_pause))
    app.add_handler(CommandHandler("resume", handlers.cmd_resume))
    app.add_handler(CommandHandler("improve", handlers.cmd_improve))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.on_text))
    return app


def run_bot() -> None:
    app = build_application()
    log.info("telegram_bot_start")
    app.run_polling()
