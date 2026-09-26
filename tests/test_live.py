"""Haqiqiy uvicorn serveri + WebSocket + haqiqiy HTTP orqali sinov (Telegram/OpenAI soxta)."""
from __future__ import annotations

import asyncio
import json
import socket

import httpx
import uvicorn
import websockets

from app.scheduler import build_scheduler
from app.web.app import _codes, create_app
from tests.conftest import ADMIN, EMP


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def test_websocket_live_events(ctx, tg):
    _codes.clear()
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="error"))
    server.install_signal_handlers = lambda: None
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.05)
        base = f"http://127.0.0.1:{port}"
        async with httpx.AsyncClient(base_url=base) as web:
            await web.post("/login/request", data={"tg_id": str(ADMIN)})
            r = await web.post("/login/verify", data={"tg_id": str(ADMIN), "code": _codes[ADMIN]["code"]})
            assert r.status_code == 303
            cookie = "; ".join(f"{k}={v}" for k, v in web.cookies.items())

            # kirmagan brauzer WebSocket ga ulana olmaydi
            try:
                async with websockets.connect(f"ws://127.0.0.1:{port}/ws"):
                    raise AssertionError("kirishsiz ulanish mumkin bo'lmasligi kerak")
            except AssertionError:
                raise
            except Exception:
                pass

            async with websockets.connect(f"ws://127.0.0.1:{port}/ws", additional_headers={"Cookie": cookie}) as ws:
                await asyncio.sleep(0.1)
                assert ctx.hub.count == 1
                # botga xodim yozsa, panel jonli hodisa oladi
                await tg.register()
                ev = json.loads(await asyncio.wait_for(ws.recv(), 3))
                assert ev["type"] == "user"
                user = await ctx.db.get_user_by_tg(EMP)
                await ctx.db.set_status(user["id"], "approved")
                await tg.text(EMP, "Salom, savolim bor")
                events = []
                for _ in range(2):
                    events.append(json.loads(await asyncio.wait_for(ws.recv(), 3)))
                assert all(e["type"] == "message" and e["user_id"] == user["id"] for e in events)
            await asyncio.sleep(0.1)
            assert ctx.hub.count == 0
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 5)


def test_scheduler_jobs(ctx):
    sch = build_scheduler(ctx.settings)
    ids = {j.id for j in sch.get_jobs()} if sch.running else None
    # ishga tushirilmagan schedulerda joblar kutilayotgan ro'yxatda bo'ladi
    pending = {j[0].id if isinstance(j, tuple) else j.id for j in getattr(sch, "_pending_jobs", [])}
    assert (ids or pending) >= {"daily", "weekly", "monthly", "remind", "quiz_tick", "faq"}
