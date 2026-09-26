"""app.main.amain ni butunlay ishga tushirib sinash (Telegram soxta, veb-server haqiqiy)."""
from __future__ import annotations

import asyncio
import socket

import httpx
import pytest
from aiogram.methods import DeleteWebhook, GetMe, GetUpdates
from aiogram.types import User

from tests.conftest import FakeSession


class PollingSession(FakeSession):
    async def make_request(self, bot, method, timeout=None):
        if isinstance(method, GetMe):
            return User(id=1, is_bot=True, first_name="Test", username="testbot")
        if isinstance(method, GetUpdates):
            await asyncio.sleep(0.2)
            return []
        return await super().make_request(bot, method, timeout)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def test_amain_runs_and_shuts_down_cleanly(tmp_path, monkeypatch):
    import app.main as main
    from aiogram import Bot

    port = _free_port()
    for k, v in {"BOT_TOKEN": "123456:TEST", "ADMIN_IDS": "1000, 2000", "OPENAI_API_KEY": "sk-test",
                 "OPENAI_VECTOR_STORE_ID": "vs_x", "WEB_PORT": str(port), "DB_PATH": str(tmp_path / "t.db"),
                 "SECRET_KEY": "k" * 32, "BASE_URL": f"http://127.0.0.1:{port}"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(main, "Bot", lambda token: Bot(token=token, session=PollingSession()))

    task = asyncio.create_task(main.amain())
    try:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as web:
            for _ in range(100):
                try:
                    r = await web.get("/health")
                    if r.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.05)
            assert r.text == "ok"
            assert "Telegram ID" in (await web.get("/login")).text
            assert (await web.get("/static/htmx.min.js")).status_code == 200
        assert not task.done()
    finally:
        task.cancel()                                     # Ctrl+C ga teng
        with pytest.raises(asyncio.CancelledError):
            await task
    assert (tmp_path / "t.db").exists()


async def test_amain_reports_missing_config(monkeypatch, tmp_path):
    import app.main as main

    for k in ("BOT_TOKEN", "ADMIN_IDS", "OPENAI_API_KEY", "OPENAI_VECTOR_STORE_ID"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(main, "load_settings", lambda: __import__("app.config", fromlist=["Settings"]).Settings())
    with pytest.raises(SystemExit):
        await main.amain()
