"""Sozlamalarni tekshiradi: .env, Telegram, OpenAI kaliti, vector store va sinov savoli.

Ishlatish:  python -m scripts.check_setup
"""
from __future__ import annotations

import asyncio
import sys

from app.agent import AgentError, TexnikumAgent
from app.config import load_settings

OK, BAD = "[OK]  ", "[XATO]"


async def main() -> int:
    s = load_settings()
    bad = 0

    def line(ok: bool, text: str):
        nonlocal bad
        print((OK if ok else BAD), text)
        bad += 0 if ok else 1

    line(bool(s.bot_token), "BOT_TOKEN kiritilgan")
    line(bool(s.admin_ids), f"ADMIN_IDS: {s.admin_ids}")
    line(bool(s.openai_api_key), "OPENAI_API_KEY kiritilgan")
    line(s.vector_store_id.startswith("vs_"), f"OPENAI_VECTOR_STORE_ID: {s.vector_store_id or '(bo`sh)'}")
    print(f"Model: {s.model} | Hisobot modeli: {s.report_model}")

    if s.bot_token:
        try:
            from aiogram import Bot

            bot = Bot(s.bot_token)
            me = await bot.get_me()
            await bot.session.close()
            line(True, f"Telegram: @{me.username} ga ulandi")
        except Exception as exc:  # noqa: BLE001
            line(False, f"Telegram: {exc}")

    if s.openai_api_key:
        agent = TexnikumAgent(s)
        try:
            vs = await agent.client.vector_stores.retrieve(s.vector_store_id)
            line(True, f"Vector store: {vs.name} | fayllar: {vs.file_counts.completed} tayyor, "
                       f"{vs.file_counts.in_progress} jarayonda, {vs.file_counts.failed} xato")
        except Exception as exc:  # noqa: BLE001
            line(False, f"Vector store o'qilmadi: {exc}")
        try:
            res = await agent.answer("Elektron jurnalda baho qo'yish uchun nima qilish kerak?", "O'qituvchi", [])
            line(True, f"Sinov savoli: found={res.found}, mavzu={res.topic}, manba={res.sources}")
            print("\nJavob:\n" + res.answer + "\n")
        except AgentError as exc:
            line(False, f"Sinov savoliga javob olinmadi: {exc}")
    print("\nHammasi joyida." if not bad else f"\n{bad} ta muammo bor. Yuqoridagilarni tuzating.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
