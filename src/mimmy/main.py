"""Mimmy CLI 엔트리포인트."""
from __future__ import annotations

import asyncio

import typer

from mimmy.config import get_settings
from mimmy.logging import setup_logging
from mimmy.secrets import hydrate_from_secrets_manager

cli = typer.Typer(add_completion=False, help="Mimmy — single-ticker LLM trading")


def _bootstrap() -> None:
    # Secrets Manager 우선 적용 (.env 는 이미 pydantic-settings가 읽음 → 덮어쓰기)
    s_preview = get_settings()
    if s_preview.use_secrets_manager:
        hydrate_from_secrets_manager(s_preview.secrets_id, s_preview.aws_region)
        # 캐시된 Settings를 비우고 다시 로드
        get_settings.cache_clear()
    setup_logging(get_settings().log_level)


@cli.command()
def loop(cycle_seconds: int = 60) -> None:
    """오케스트레이터 루프만 실행."""
    _bootstrap()
    from mimmy.runtime.loop import run_loop

    asyncio.run(run_loop(cycle_seconds=cycle_seconds))


@cli.command()
def bot() -> None:
    """텔레그램 봇만 실행."""
    _bootstrap()
    from mimmy.telegram_bot import run_bot

    run_bot()


@cli.command()
def dashboard() -> None:
    """대시보드만 실행."""
    _bootstrap()
    from mimmy.dashboard import run_dashboard

    run_dashboard()


@cli.command()
def run() -> None:
    """루프 + 봇 + 대시보드를 한 프로세스에서 실행 (개발용).
    운영에선 각 서비스를 분리된 systemd unit으로 돌릴 것을 권장."""
    _bootstrap()

    async def _main() -> None:
        from mimmy.dashboard import create_app
        from mimmy.runtime.loop import run_loop
        from mimmy.telegram_bot import build_application
        import uvicorn

        settings = get_settings()

        bot_app = build_application()
        await bot_app.initialize()
        await bot_app.start()
        await bot_app.updater.start_polling()

        config = uvicorn.Config(
            create_app(),
            host=settings.dashboard_host,
            port=settings.dashboard_port,
            log_level=settings.log_level.lower(),
        )
        server = uvicorn.Server(config)

        await asyncio.gather(run_loop(), server.serve())

    asyncio.run(_main())


if __name__ == "__main__":
    cli()
