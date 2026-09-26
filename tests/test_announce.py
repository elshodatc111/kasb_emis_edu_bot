from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest
from aiogram.methods import SendMessage, SendPhoto

from app import announce
from tests.conftest import ADMIN, EMP
from tests.test_web import login, make_user, web  # noqa: F401


async def _second_user(ctx, tg, uid=3000, role_idx=1):
    await tg.register(uid, role_idx)
    u = await ctx.db.get_user_by_tg(uid)
    await ctx.db.set_status(u["id"], "approved")
    return await ctx.db.get_user(u["id"])


async def test_text_announcement_to_all(web, ctx, tg):  # noqa: F811
    csrf = await login(web, ctx)
    u1 = await make_user(ctx, tg)
    await _second_user(ctx, tg)
    r = await web.post("/announcements/preview", headers={"X-CSRF-Token": csrf},
                       data={"kind": "important", "title": "Texnik ish", "text": "Ertaga 10:00 da tizim o'chadi.",
                             "aud_mode": "all"})
    m = re.search(r"/announcements/(\d+)", r.headers["HX-Redirect"])
    ann_id = int(m.group(1))
    # admin uchun oldindan ko'rish yuborilgan
    assert any("Oldindan ko'rish" in t for t in ctx.session.texts_to(ADMIN))
    page = await web.get(f"/announcements/{ann_id}")
    assert "MUHIM OGOHLANTIRISH" in page.text and "Texnik ish" in page.text
    r = await web.post(f"/announcements/{ann_id}/send", headers={"X-CSRF-Token": csrf})
    assert "HX-Redirect" in r.headers
    await announce.wait_all()
    for uid in (EMP, 3000):
        texts = ctx.session.texts_to(uid)
        assert any("MUHIM OGOHLANTIRISH" in t and "Ertaga 10:00" in t for t in texts)
    st = await ctx.db.announcement_stats(ann_id)
    assert st["sent"] == 2 and st["failed"] == 0
    assert (await ctx.db.get_announcement(ann_id))["status"] == "sent"
    # ikkinchi marta yuborib bo'lmaydi
    assert await announce.start(ann_id) is False
    sent_before = len(ctx.session.sent(SendMessage))
    await announce.tick()
    await announce.wait_all()
    assert len(ctx.session.sent(SendMessage)) == sent_before
    assert "Yetdi" in (await web.get(f"/announcements/{ann_id}")).text
    assert u1["id"]


async def test_image_with_caption_and_ack(web, ctx, tg):  # noqa: F811
    csrf = await login(web, ctx)
    await make_user(ctx, tg)
    r = await web.post("/announcements/preview", headers={"X-CSRF-Token": csrf},
                       data={"kind": "info", "text": "Yangi qo'llanma", "aud_mode": "all", "ack": "on"},
                       files={"image": ("a.png", b"\x89PNG-bytes", "image/png")})
    ann_id = int(re.search(r"/announcements/(\d+)", r.headers["HX-Redirect"]).group(1))
    ann = await ctx.db.get_announcement(ann_id)
    assert ann["image_file_id"] == "PH_SENT" and ann["ack_required"] == 1
    photos = ctx.session.sent(SendPhoto)
    assert photos and photos[0].chat_id == ADMIN  # oldindan ko'rish adminning o'ziga
    await web.post(f"/announcements/{ann_id}/send", headers={"X-CSRF-Token": csrf})
    await announce.wait_all()
    to_emp = [p for p in ctx.session.sent(SendPhoto) if p.chat_id == EMP]
    assert len(to_emp) == 1 and "Yangi qo'llanma" in to_emp[0].caption and to_emp[0].reply_markup
    # tugmani bosish
    await tg.callback(EMP, f"ann:{ann_id}")
    assert (await ctx.db.announcement_stats(ann_id))["acked"] == 1
    await tg.callback(EMP, f"ann:{ann_id}")  # takroriy bosish zarar qilmaydi
    assert (await ctx.db.announcement_stats(ann_id))["acked"] == 1
    assert (await web.get(f"/announcements/{ann_id}/image")).content == b"FAKE-IMAGE-BYTES"


async def test_image_only(web, ctx, tg):  # noqa: F811
    csrf = await login(web, ctx)
    await make_user(ctx, tg)
    r = await web.post("/announcements/preview", headers={"X-CSRF-Token": csrf},
                       data={"kind": "info", "aud_mode": "all"}, files={"image": ("a.jpg", b"x", "image/jpeg")})
    assert "HX-Redirect" in r.headers


async def test_validation(web, ctx, tg):  # noqa: F811
    csrf = await login(web, ctx)
    await make_user(ctx, tg)
    h = {"X-CSRF-Token": csrf}
    r = await web.post("/announcements/preview", headers=h, data={"kind": "info", "aud_mode": "all"})
    assert "Matn yoki rasm" in r.text
    long = "a" * 1000
    r = await web.post("/announcements/preview", headers=h, data={"kind": "info", "text": long, "aud_mode": "all"},
                       files={"image": ("a.jpg", b"x", "image/jpeg")})
    assert "1024" in r.text and not r.headers.get("HX-Redirect")
    r = await web.post("/announcements/preview", headers=h, data={"kind": "info", "text": long, "aud_mode": "all"})
    assert "HX-Redirect" in r.headers  # matn uchun 1024 chegarasi yo'q
    r = await web.post("/announcements/preview", headers=h,
                       data={"kind": "info", "text": "PINFL 12345678901234", "aud_mode": "all"})
    assert "PINFL" in r.text and not r.headers.get("HX-Redirect")
    r = await web.post("/announcements/preview", headers=h, data={"kind": "info", "text": "x", "aud_mode": "roles"})
    assert "rolni" in r.text
    r = await web.post("/announcements/preview", headers=h, data={"kind": "info", "text": "x", "aud_mode": "all"},
                       files={"image": ("a.txt", b"x", "text/plain")})
    assert "rasm" in r.text.lower()
    r = await web.post("/announcements/preview", data={"kind": "info", "text": "x"})
    assert r.status_code == 403


async def test_roles_and_users_audience(web, ctx, tg):  # noqa: F811
    csrf = await login(web, ctx)
    await make_user(ctx, tg)                     # role_idx 0 = O'qituvchi
    u2 = await _second_user(ctx, tg, 3000, 1)    # O'quv bo'limi
    h = {"X-CSRF-Token": csrf}
    r = await web.post("/announcements/preview", headers=h,
                       data={"kind": "info", "text": "Faqat o'qituvchilarga", "aud_mode": "roles", "roles": "O'qituvchi"})
    a1 = int(re.search(r"/announcements/(\d+)", r.headers["HX-Redirect"]).group(1))
    r = await web.post("/announcements/preview", headers=h,
                       data={"kind": "reminder", "text": "Shaxsan sizga", "aud_mode": "users", "users": str(u2["id"])})
    a2 = int(re.search(r"/announcements/(\d+)", r.headers["HX-Redirect"]).group(1))
    await web.post(f"/announcements/{a1}/send", headers=h)
    await web.post(f"/announcements/{a2}/send", headers=h)
    await announce.wait_all()
    assert any("Faqat o'qituvchilarga" in t for t in ctx.session.texts_to(EMP))
    assert not any("Faqat o'qituvchilarga" in t for t in ctx.session.texts_to(3000))
    assert any("Shaxsan sizga" in t for t in ctx.session.texts_to(3000))
    assert not any("Shaxsan sizga" in t for t in ctx.session.texts_to(EMP))


async def test_pending_users_excluded(web, ctx, tg):  # noqa: F811
    csrf = await login(web, ctx)
    await make_user(ctx, tg, approve=False)
    r = await web.post("/announcements/preview", headers={"X-CSRF-Token": csrf},
                       data={"kind": "info", "text": "x", "aud_mode": "all"})
    assert "tasdiqlangan xodim yo" in r.text


async def test_schedule_and_tick(web, ctx, tg):  # noqa: F811
    csrf = await login(web, ctx)
    await make_user(ctx, tg)
    h = {"X-CSRF-Token": csrf}
    r = await web.post("/announcements/preview", headers=h, data={"kind": "info", "text": "Rejali", "aud_mode": "all"})
    ann_id = int(re.search(r"/announcements/(\d+)", r.headers["HX-Redirect"]).group(1))
    past = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
    r = await web.post(f"/announcements/{ann_id}/schedule", headers=h, data={"when": past})
    assert "kelajakda" in r.text
    fut = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
    r = await web.post(f"/announcements/{ann_id}/schedule", headers=h, data={"when": fut})
    assert "HX-Redirect" in r.headers
    assert (await ctx.db.get_announcement(ann_id))["status"] == "scheduled"
    assert await announce.tick() == 0
    assert not any("Rejali" in t for t in ctx.session.texts_to(EMP))
    # vaqt kelgan deb hisoblaymiz
    await ctx.db._exec("UPDATE announcements SET scheduled_at='2000-01-01 00:00:00' WHERE id=?", (ann_id,))
    assert await announce.tick() == 1
    await announce.wait_all()
    assert any("Rejali" in t for t in ctx.session.texts_to(EMP))
    assert (await ctx.db.get_announcement(ann_id))["status"] == "sent"


async def test_blocked_user_marked_failed(web, ctx, tg, monkeypatch):  # noqa: F811
    from aiogram.exceptions import TelegramForbiddenError
    from aiogram.methods import SendMessage as SM

    csrf = await login(web, ctx)
    await make_user(ctx, tg)
    await _second_user(ctx, tg)
    orig = ctx.session.make_request

    async def fake(bot, method, timeout=None):
        if isinstance(method, SM) and method.chat_id == 3000 and "Bloklangan" in (method.text or ""):
            raise TelegramForbiddenError(method=method, message="Forbidden: bot was blocked by the user")
        return await orig(bot, method, timeout)

    monkeypatch.setattr(ctx.session, "make_request", fake)
    r = await web.post("/announcements/preview", headers={"X-CSRF-Token": csrf},
                       data={"kind": "info", "text": "Bloklangan test", "aud_mode": "all"})
    ann_id = int(re.search(r"/announcements/(\d+)", r.headers["HX-Redirect"]).group(1))
    await web.post(f"/announcements/{ann_id}/send", headers={"X-CSRF-Token": csrf})
    await announce.wait_all()
    st = await ctx.db.announcement_stats(ann_id)
    assert st["sent"] == 1 and st["failed"] == 1
    assert any("1/2" in t for t in ctx.session.texts_to(ADMIN))


async def test_copy_delete_and_pages(web, ctx, tg):  # noqa: F811
    csrf = await login(web, ctx)
    await make_user(ctx, tg)
    h = {"X-CSRF-Token": csrf}
    assert "E'lonlar" in (await web.get("/announcements")).text
    assert (await web.get("/announcements/new")).status_code == 200
    r = await web.post("/announcements/preview", headers=h, data={"kind": "info", "text": "Nusxa", "aud_mode": "all"})
    ann_id = int(re.search(r"/announcements/(\d+)", r.headers["HX-Redirect"]).group(1))
    assert "Nusxa" in (await web.get(f"/announcements/new?copy={ann_id}")).text
    assert (await web.get("/announcements/9999")).status_code == 404
    await web.post(f"/announcements/{ann_id}/delete", headers=h)
    assert await ctx.db.get_announcement(ann_id) is None
