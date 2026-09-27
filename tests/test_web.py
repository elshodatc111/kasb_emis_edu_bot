from __future__ import annotations

import os
import re

import httpx
import pytest
from aiogram.methods import SendMessage, SendPhoto, SendVideo
from starlette.testclient import TestClient

from app.web.app import _codes, create_app
from tests.conftest import ADMIN, EMP


@pytest.fixture
async def web(ctx):
    _codes.clear()
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def login(web, ctx, tg_id=ADMIN):
    r = await web.post("/login/request", data={"tg_id": str(tg_id)})
    assert r.status_code == 200
    code = _codes[tg_id]["code"]
    r = await web.post("/login/verify", data={"tg_id": str(tg_id), "code": code})
    assert r.status_code == 303
    page = await web.get("/")
    assert page.status_code == 200
    return re.search(r'X-CSRF-Token": "([0-9a-f]+)"', page.text).group(1)


async def make_user(ctx, tg, approve=True):
    await tg.register()
    user = await ctx.db.get_user_by_tg(EMP)
    if approve:
        await ctx.db.set_status(user["id"], "approved")
    return await ctx.db.get_user(user["id"])


async def test_requires_login(web):
    for path in ("/", "/users", "/chats", "/reports", "/videos", "/media/1"):
        r = await web.get(path)
        assert r.status_code == 303 and r.headers["location"] == "/login", path
    r = await web.post("/users/1/status", data={"status": "approved"}, headers={"HX-Request": "true"})
    assert r.headers.get("HX-Redirect") == "/login"
    assert (await web.get("/health")).text == "ok"


async def test_login_code_sent_via_telegram_only_to_admins(web, ctx):
    r = await web.post("/login/request", data={"tg_id": str(ADMIN)})
    assert "6 xonali kod" in r.text
    codes = [t for t in ctx.session.texts_to(ADMIN) if "kirish kodi" in t]
    assert len(codes) == 1
    # admin bo'lmagan ID: bir xil javob, lekin kod yuborilmaydi
    r2 = await web.post("/login/request", data={"tg_id": "555"})
    assert "6 xonali kod" in r2.text and _codes.get(555) is None
    assert ctx.session.texts_to(555) == []
    # noto'g'ri kod
    bad = await web.post("/login/verify", data={"tg_id": str(ADMIN), "code": "000000"})
    assert bad.status_code == 401
    # 5 marta noto'g'ri urinishdan keyin to'g'ri kod ham ishlamaydi
    real = _codes[ADMIN]["code"]
    for _ in range(5):
        await web.post("/login/verify", data={"tg_id": str(ADMIN), "code": "111111" if real != "111111" else "222222"})
    ok = await web.post("/login/verify", data={"tg_id": str(ADMIN), "code": real})
    assert ok.status_code == 401


async def test_csrf_enforced(web, ctx, tg):
    csrf = await login(web, ctx)
    user = await make_user(ctx, tg, approve=False)
    r = await web.post(f"/users/{user['id']}/status", data={"status": "approved"})
    assert r.status_code == 403
    r = await web.post(f"/users/{user['id']}/status", data={"status": "approved"}, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200 and "Ruxsat berilgan" in r.text
    assert (await ctx.db.get_user(user["id"]))["status"] == "approved"
    assert any("ruxsat berildi" in t for t in ctx.session.texts_to(EMP))


async def test_users_and_dashboard_pages(web, ctx, tg):
    await login(web, ctx)
    await make_user(ctx, tg, approve=False)
    r = await web.get("/users?status=pending")
    assert "Valiyev Ali Karimovich" in r.text and "Ruxsat berish" in r.text
    r = await web.get("/")
    assert "Kutilayotgan so'rovlar" in r.text and "Valiyev Ali" in r.text
    r = await web.get("/users?q=transport")
    assert "Valiyev" in r.text
    r = await web.get("/users?q=yoq-narsa")
    assert "Foydalanuvchilar topilmadi" in r.text


async def test_chat_view_and_incremental_messages(web, ctx, tg):
    await login(web, ctx)
    user = await make_user(ctx, tg)
    await tg.text(EMP, "Jurnalga baho qanday qo'yiladi?")
    await tg.photo(EMP, caption="Mana xato <script>alert(1)</script>")
    r = await web.get(f"/chats/{user['id']}")
    assert r.status_code == 200
    assert "Jurnalga baho qanday" in r.text and f'src="/media/' in r.text
    assert "<script>alert(1)</script>" not in r.text and "&lt;script&gt;" in r.text   # XSS himoyasi
    assert (await ctx.db.get_user(user["id"]))["unread"] == 0
    msgs = await ctx.db.list_messages(user["id"])
    last = msgs[-1]["id"]
    r = await web.get(f"/chats/{user['id']}/messages", params={"after": last})
    assert 'class="msg' not in r.text                      # yangi xabar yo'q
    await tg.text(EMP, "Yana savol")
    r = await web.get(f"/chats/{user['id']}/messages", params={"after": last})
    assert "Yana savol" in r.text and "Jurnalga baho" not in r.text
    r = await web.get("/chats?filter=attention")
    assert "Valiyev Ali" in r.text


async def test_media_proxy_reads_from_telegram_in_memory(web, ctx, tg):
    await login(web, ctx)
    user = await make_user(ctx, tg)
    await tg.photo(EMP)
    photo = [m for m in await ctx.db.list_messages(user["id"]) if m["kind"] == "photo"][0]
    r = await web.get(f"/media/{photo['id']}")
    assert r.status_code == 200 and r.content == b"FAKE-IMAGE-BYTES"
    assert r.headers["content-type"] == "image/jpeg" and r.headers["cache-control"] == "no-store"
    assert (await web.get("/media/99999")).status_code == 404
    text_msg = await ctx.db.add_message(user["id"], "user", "text", text="x")
    assert (await web.get(f"/media/{text_msg}")).status_code == 404


async def test_admin_sends_text_photo_video(web, ctx, tg, tmp_path, monkeypatch):
    csrf = await login(web, ctx)
    user = await make_user(ctx, tg)
    monkeypatch.chdir(tmp_path)
    h = {"X-CSRF-Token": csrf}
    r = await web.post(f"/chats/{user['id']}/send", data={"text": "Salom, yordam beraman"}, headers=h)
    assert r.status_code == 200 and r.headers["hx-trigger"] == "refresh-msgs,list-refresh"
    assert any("Salom, yordam beraman" in t and "Administrator" in t for t in ctx.session.texts_to(EMP))

    r = await web.post(f"/chats/{user['id']}/send", data={"text": "Mana ko'rsatma"}, headers=h,
                       files={"file": ("shot.png", b"\x89PNG-data", "image/png")})
    assert r.headers.get("hx-trigger")
    photo = ctx.session.sent(SendPhoto)[0]
    assert "Mana ko'rsatma" in photo.caption and "Administrator" in photo.caption and photo.photo.data == b"\x89PNG-data"

    r = await web.post(f"/chats/{user['id']}/send", data={"text": ""}, headers=h,
                       files={"file": ("demo.mp4", b"video-bytes", "video/mp4")})
    assert r.headers.get("hx-trigger")
    assert ctx.session.sent(SendVideo)[0].video.data == b"video-bytes"

    msgs = [m for m in await ctx.db.list_messages(user["id"]) if m["sender"] == "admin"]
    assert [m["kind"] for m in msgs] == ["text", "photo", "video"]
    assert msgs[1]["file_id"] == "PH_SENT" and msgs[2]["file_id"] == "VID_SENT"
    # admin javob bergach suhbat admin rejimiga o'tadi, diqqat belgisi olinadi
    u = await ctx.db.get_user(user["id"])
    assert u["mode"] == "admin" and u["needs_attention"] == 0
    # hech qanday fayl diskka yozilmadi
    assert [p for p in os.listdir(tmp_path)] == []


async def test_admin_send_validation(web, ctx, tg):
    csrf = await login(web, ctx)
    user = await make_user(ctx, tg)
    h = {"X-CSRF-Token": csrf}
    r = await web.post(f"/chats/{user['id']}/send", data={"text": ""}, headers=h)
    assert "Xabar bo'sh" in r.text
    r = await web.post(f"/chats/{user['id']}/send", data={"text": ""}, headers=h,
                       files={"file": ("a.pdf", b"x", "application/pdf")})
    assert "Faqat rasm" in r.text
    r = await web.post(f"/chats/{user['id']}/send", data={"text": ""}, headers=h,
                       files={"file": ("a.png", b"0" * (10 * 1024 * 1024 + 1), "image/png")})
    assert "juda katta" in r.text
    assert ctx.session.sent(SendPhoto) == []


async def test_mode_toggle_and_attention(web, ctx, tg):
    csrf = await login(web, ctx)
    user = await make_user(ctx, tg)
    h = {"X-CSRF-Token": csrf}
    r = await web.post(f"/chats/{user['id']}/mode", data={"mode": "admin"}, headers=h)
    assert "Admin suhbatda" in r.text and "Botga qaytarish" in r.text
    await ctx.db.set_attention(user["id"], True)
    r = await web.post(f"/chats/{user['id']}/mode", data={"mode": "bot"}, headers=h)
    assert "Bot javob beradi" in r.text
    assert (await ctx.db.get_user(user["id"]))["needs_attention"] == 0
    assert (await web.post(f"/chats/{user['id']}/mode", data={"mode": "x"}, headers=h)).status_code == 400


async def test_suggest_reply_is_escaped(web, ctx, tg):
    csrf = await login(web, ctx)
    user = await make_user(ctx, tg)
    r = await web.post(f"/chats/{user['id']}/suggest", headers={"X-CSRF-Token": csrf})
    assert "Taklif qilingan javob &lt;b&gt;" in r.text and 'id="msg-text"' in r.text


async def test_reports_and_videos_pages(web, ctx, tg):
    csrf = await login(web, ctx)
    user = await make_user(ctx, tg)
    for q in ("Jurnal savoli 1", "Jurnal savoli 2 (PINFL 51805055530014)", "Jurnal savoli 3"):
        await tg.text(EMP, q)
    h = {"X-CSRF-Token": csrf, "HX-Request": "true"}
    r = await web.post("/reports/generate", data={"kind": "daily"}, headers=h)
    loc = r.headers["hx-redirect"]
    assert loc.startswith("/reports/")
    page = await web.get(loc)
    assert "Asosiy xulosa" in page.text and "Elektron jurnal" in page.text
    label, stats, samples = ctx.agent.reports[0]
    assert stats["questions"] == 3
    assert "51805055530014" not in str(samples)                      # hisobotga ham asl PINFL ketmaydi
    assert "Hisobotlar" in (await web.get("/reports")).text

    r = await web.post("/videos/generate", data={"kind": "daily"}, headers=h)
    assert "/videos?notice=" in r.headers["hx-redirect"]
    page = await web.get("/videos")
    assert "Elektron jurnal bo&#39;yicha qo&#39;llanma" in page.text or "Elektron jurnal bo'yicha qo'llanma" in page.text
    assert "51805055530014" not in str(ctx.agent.videos)
    plan = (await ctx.db.list_video_plans())[0]
    d = await web.get(f"/videos/{plan['id']}/download")
    assert d.status_code == 200 and "attachment" in d.headers["content-disposition"] and "# Video rolik" in d.text
    assert (await web.post("/reports/generate", data={"kind": "zzz"}, headers=h)).status_code == 400


async def test_websocket_requires_admin_session(ctx):
    app = create_app()
    with TestClient(app) as c:
        with pytest.raises(Exception):
            with c.websocket_connect("/ws"):
                pass


async def test_logout(web, ctx):
    await login(web, ctx)
    r = await web.get("/logout")
    assert r.status_code == 303
    assert (await web.get("/users")).status_code == 303
