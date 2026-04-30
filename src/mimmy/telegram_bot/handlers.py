from __future__ import annotations

from telegram import Update
from telegram.ext import Application, ContextTypes

from mimmy.config import get_settings
from mimmy.logging import get_logger
from mimmy.telegram_bot.auth import reject_if_unauthorized

log = get_logger(__name__)


COMMANDS: list[tuple[str, str]] = [
    ("/start", "봇 동작 확인 + 거래 대상 요약"),
    ("/help", "명령어 목록 보기"),
    ("/status", "오케스트레이터 최신 상태"),
    ("/positions", "현재 포지션"),
    ("/pause", "거래 루프 일시정지"),
    ("/resume", "거래 루프 재개"),
    ("/improve <지시>", "자연어 코드 개선 요청 (self-edit 파이프라인)"),
]


def _help_text() -> str:
    lines = ["사용 가능한 명령어:"]
    lines.extend(f"{cmd} — {desc}" for cmd, desc in COMMANDS)
    return "\n".join(lines)


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_if_unauthorized(update, ctx):
        return
    s = get_settings()
    await update.message.reply_text(
        f"Mimmy online.\n"
        f"- 대상: {s.market.value}:{s.ticker}\n"
        f"- env: {s.env}\n\n"
        f"{_help_text()}"
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_if_unauthorized(update, ctx):
        return
    await update.message.reply_text(_help_text())


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_if_unauthorized(update, ctx):
        return
    # TODO: 실제 오케스트레이터의 최신 상태 조회
    await update.message.reply_text("status: running (stub)")


async def cmd_positions(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_if_unauthorized(update, ctx):
        return
    # TODO: Portfolio 조회
    await update.message.reply_text("positions: (stub)")


async def cmd_pause(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_if_unauthorized(update, ctx):
        return
    await update.message.reply_text("paused (stub)")


async def cmd_resume(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_if_unauthorized(update, ctx):
        return
    await update.message.reply_text("resumed (stub)")


async def cmd_improve(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """자연어 코드 개선 명령 — self_edit 파이프라인으로 위임."""
    if await reject_if_unauthorized(update, ctx):
        return
    instruction = " ".join(ctx.args or [])
    if not instruction:
        await update.message.reply_text("사용법: /improve <자연어 지시>")
        return

    from mimmy.self_edit.pipeline import propose_change

    await update.message.reply_text("변경안을 준비 중… 잠시만요.")
    result = await propose_change(instruction, requested_by=str(update.effective_user.id))
    await update.message.reply_text(result.summary_for_user())


async def notify_startup(app: Application) -> None:
    """봇 부팅 직후 authorized 사용자들에게 시작 알림과 대시보드 접근 안내를 보낸다."""
    s = get_settings()
    ids = s.authorized_ids
    if not ids:
        log.info("startup_notify_skipped_no_authorized_ids")
        return

    host_hint = await _public_host_hint()
    tunnel_cmd = (
        f"ssh -i ~/kitty-key.pem -L {s.dashboard_port}:localhost:{s.dashboard_port} ubuntu@{host_hint}"
        if host_hint
        else f"ssh -L {s.dashboard_port}:localhost:{s.dashboard_port} ubuntu@<EC2_IP>"
    )
    text = (
        "mimmy 서버 시작\n"
        f"- 대상: {s.market.value}:{s.ticker}\n"
        f"- env: {s.env}\n"
        f"- broker: {s.broker}\n"
        "\n"
        "대시보드 (SSH 터널 필요):\n"
        f"  $ {tunnel_cmd}\n"
        f"  http://localhost:{s.dashboard_port}\n"
        "\n"
        "/help 으로 명령어 확인."
    )
    for uid in ids:
        try:
            await app.bot.send_message(chat_id=uid, text=text)
        except Exception as e:
            log.warning("startup_notify_send_failed", chat_id=uid, error=str(e))


async def _public_host_hint() -> str:
    """EC2 IMDSv2로 퍼블릭 IPv4를 조회. EC2 외 환경에선 빈 문자열."""
    import asyncio

    import httpx

    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            tok = await client.put(
                "http://169.254.169.254/latest/api/token",
                headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"},
            )
            tok.raise_for_status()
            ip = await client.get(
                "http://169.254.169.254/latest/meta-data/public-ipv4",
                headers={"X-aws-ec2-metadata-token": tok.text},
            )
            ip.raise_for_status()
            return ip.text.strip()
    except (httpx.HTTPError, asyncio.TimeoutError):
        return ""


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """명령어 외 자유 텍스트. 기본은 'improve'로 취급한다."""
    if await reject_if_unauthorized(update, ctx):
        return
    text = (update.message.text or "").strip()
    if not text:
        return
    from mimmy.self_edit.pipeline import propose_change

    await update.message.reply_text("지시 반영 중…")
    result = await propose_change(text, requested_by=str(update.effective_user.id))
    await update.message.reply_text(result.summary_for_user())
