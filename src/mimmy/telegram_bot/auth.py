from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from mimmy.config import get_settings
from mimmy.logging import get_logger

log = get_logger(__name__)


def is_authorized(update: Update) -> bool:
    allowed = get_settings().authorized_ids
    user = update.effective_user
    if not user:
        return False
    if not allowed:
        log.warning("no AUTHORIZED_TELEGRAM_IDS set — rejecting all traffic")
        return False
    return user.id in allowed


async def reject_if_unauthorized(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    if is_authorized(update):
        return False
    if update.effective_chat:
        await ctx.bot.send_message(update.effective_chat.id, "권한이 없습니다.")
    log.warning("unauthorized_telegram", user=update.effective_user and update.effective_user.id)
    return True
