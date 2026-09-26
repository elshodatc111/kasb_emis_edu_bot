from __future__ import annotations

import asyncio
import contextlib
import logging
import sys

import uvicorn
from aiogram import Bot

from .agent import TexnikumAgent
from .bot import build_dispatcher
from .config import load_settings
from .context import Context, set_ctx
from .db import Database
from .hub import Hub
from .scheduler import build_scheduler
from .web.app import create_app

log = logging.getLogger("texnikum")


class _Server(uvicorn.Server):
    """Signal (Ctrl+C) ni asyncio.run boshqaradi, shuning uchun uvicorn signal handlerlari o'chirilgan."""

    def install_signal_handlers(self) -> None:  # eski uvicorn
        pass

    @contextlib.contextmanager
    def capture_signals(self):  # yangi uvicorn
        yield


def _fail(msg: str) -> None:
    print(f"\nXATO: {msg}\n", file=sys.stderr)
    sys.exit(1)


async def amain() -> None:
    settings = load_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)

    if not settings.bot_token:
        _fail(".env faylida BOT_TOKEN ko'rsatilmagan (@BotFather dan oling).")
    if not settings.admin_ids:
        _fail(".env faylida ADMIN_IDS ko'rsatilmagan (kamida bitta Telegram ID kerak).")
    if not settings.openai_api_key:
        _fail(".env faylida OPENAI_API_KEY ko'rsatilmagan.")
    if not settings.vector_store_id:
        _fail(".env faylida OPENAI_VECTOR_STORE_ID ko'rsatilmagan (vs_... bilan boshlanadi).")

    db = Database(settings.db_file)
    await db.connect()
    bot = Bot(token=settings.bot_token)
    agent = TexnikumAgent(settings)
    hub = Hub()
    set_ctx(Context(settings=settings, db=db, bot=bot, agent=agent, hub=hub))

    dp = build_dispatcher()
    app = create_app()
    scheduler = build_scheduler(settings)

    try:
        me = await bot.get_me()
    except Exception as exc:  # noqa: BLE001
        await db.close()
        _fail(f"Telegram'ga ulanib bo'lmadi (BOT_TOKEN to'g'rimi? internet bormi?): {exc}")
    await bot.delete_webhook(drop_pending_updates=False)
    log.info("Bot ishga tushdi: @%s | Panel: %s | Adminlar: %s", me.username, settings.base_url, settings.admin_ids)

    scheduler.start()
    server = _Server(uvicorn.Config(app, host=settings.web_host, port=settings.web_port, log_level="warning",
                                    access_log=False))
    web_task = asyncio.create_task(server.serve(), name="web")
    bot_task = asyncio.create_task(
        dp.start_polling(bot, handle_signals=False, allowed_updates=dp.resolve_used_update_types()), name="bot")
    print(f"\nTayyor. Veb-panel: {settings.base_url}  (to'xtatish: Ctrl+C)\n")
    try:
        done, _pending = await asyncio.wait({web_task, bot_task}, return_when=asyncio.FIRST_COMPLETED)
        for t in done:
            if t.exception():
                log.error("%s to'xtadi: %r", t.get_name(), t.exception())
    finally:
        server.should_exit = True
        for t in (bot_task, web_task):
            t.cancel()
        await asyncio.gather(bot_task, web_task, return_exceptions=True)
        scheduler.shutdown(wait=False)
        await bot.session.close()
        await db.close()
        log.info("To'xtatildi")


def main() -> None:
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
