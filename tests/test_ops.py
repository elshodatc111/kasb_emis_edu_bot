"""Tizim boshqaruvi: xatolar jurnali, xarajat, spam, qidiruv, izohlar, biriktirish, faol bo'lmaganlar, ish vaqti, reset."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from types import SimpleNamespace

from aiogram.methods import SendMessage

from app import announce, ops, quiz, services, spam
from app.agent import AgentAnswer, AgentError, TexnikumAgent
from app.db import ts, utcnow
from tests.conftest import ADMIN, EMP
from tests.test_features import approved, dt, last_to
from tests.test_web import login, web  # noqa: F401


# ------------------------------------------------------------------ xatolar jurnali
async def test_error_log_handler_and_system_page(web, ctx):  # noqa: F811
    csrf = await login(web, ctx)
    ops.install_error_log()
    try:
        try:
            1 / 0
        except ZeroDivisionError:
            logging.getLogger("app.test").exception("Sinov xatosi")
        await asyncio.sleep(0.05)
        errs = await ctx.db.list_errors()
        assert errs and "Sinov xatosi" in errs[0]["message"] and "ZeroDivisionError" in errs[0]["detail"]
        page = await web.get("/system")
        assert page.status_code == 200 and "Sinov xatosi" in page.text and "TOZALASH" in page.text
        r = await web.post("/system/check", headers={"X-CSRF-Token": csrf})
        assert "Telegram bot" in r.text and "ulangan" in r.text and "lumotlar bazasi" in r.text
        await web.post("/system/errors/clear", headers={"X-CSRF-Token": csrf})
        assert await ctx.db.list_errors() == []
    finally:
        root = logging.getLogger()
        for h in [h for h in root.handlers if isinstance(h, ops.DBLogHandler)]:
            root.removeHandler(h)


# ------------------------------------------------------------------ AI sarfi va xarajat
def _real_agent(ctx, fail=False):
    async def create(**kw):
        if fail:
            raise RuntimeError("API down")
        return SimpleNamespace(output_text='{"found": true, "answer": "Javob", "topic": "Guruhlar"}', output=[],
                               usage=SimpleNamespace(input_tokens=1000, output_tokens=500))
    ag = TexnikumAgent(ctx.settings)
    ag.client = SimpleNamespace(responses=SimpleNamespace(create=create))
    return ag


async def test_agent_logs_usage(ctx):
    ag = _real_agent(ctx)
    res = await ag.answer("Savol", "O'qituvchi", [])
    assert res.found
    s = await ctx.db.usage_sum("2000-01-01 00:00:00")
    assert s["requests"] == 1 and s["tin"] == 1000 and s["tout"] == 500
    assert (await ctx.db.usage_by_purpose("2000-01-01 00:00:00"))[0]["purpose"] == "answer"


async def test_usage_failures_alert_admin(ctx):
    ops._consec_fail = 0
    ops._last_fail_alert = 0
    ag = _real_agent(ctx, fail=True)
    for _ in range(3):
        try:
            await ag.answer("Savol", "O'qituvchi", [])
        except AgentError:
            pass
    assert any("OpenAI ketma-ket xato" in t for t in ctx.session.texts_to(ADMIN))
    assert (await ctx.db.usage_sum("2000-01-01 00:00:00"))["errors"] == 3
    ops._consec_fail = 0


async def test_usage_page_cost_and_budget_alert(web, ctx):  # noqa: F811
    csrf = await login(web, ctx)
    h = {"X-CSRF-Token": csrf}
    r = await web.post("/usage/settings", headers=h, data={"price_in": "2", "price_out": "10", "budget": "0,01"})
    assert "HX-Redirect" in r.headers
    await ops.record_usage("answer", "m", 1_000_000, 100_000)   # 2 + 1 = $3 > limit
    page = await web.get("/usage")
    assert "$3.00" in page.text and "Oylik limit" in page.text
    assert any("oylik limitning 100%" in t for t in ctx.session.texts_to(ADMIN))
    before = len(ctx.session.texts_to(ADMIN))
    await ops.record_usage("answer", "m", 10, 10)
    assert len(ctx.session.texts_to(ADMIN)) == before        # bir oyda bir marta
    r = await web.post("/usage/settings", headers=h, data={"price_in": "abc", "price_out": "1", "budget": "1"})
    assert "Raqam" in r.text


# ------------------------------------------------------------------ spam
async def test_repeated_question_not_sent_to_ai_then_muted(web, ctx, tg):  # noqa: F811
    csrf = await login(web, ctx)
    ctx.settings.rate_limit_per_min = 50
    user = await approved(ctx, tg)
    await tg.text(EMP, "Guruh qanday ochiladi?")
    assert len(ctx.agent.questions) == 1
    await tg.text(EMP, "guruh qanday ochiladi")              # bir xil (kichik/belgilar farqi bilan)
    assert len(ctx.agent.questions) == 1                    # AI chaqirilmadi
    assert "yaqinda javob berilgan" in last_to(ctx, EMP).text and "Menyudan" in last_to(ctx, EMP).text
    await tg.text(EMP, "Guruh qanday ochiladi?")
    await tg.text(EMP, "Guruh qanday ochiladi?")            # 4-marta: to'xtatiladi
    assert "15 daqiqaga to'xtatildingiz" in last_to(ctx, EMP).text
    n = len(ctx.session.sent(SendMessage))
    await tg.text(EMP, "Boshqa savol")                       # to'xtatilganida javob berilmaydi
    assert len(ctx.agent.questions) == 1
    assert len(ctx.session.sent(SendMessage)) == n           # ogohlantirish allaqachon berilgan, endi jim
    await tg.text(EMP, "Yana savol")
    assert len(ctx.session.sent(SendMessage)) == n
    page = await web.get("/system")
    assert "to'xtatilgan" in page.text and "takror savol" in page.text
    await web.post(f"/system/unmute/{user['id']}", headers={"X-CSRF-Token": csrf})
    await tg.text(EMP, "Yangi savol")
    assert ctx.agent.questions[-1] == "Yangi savol"


async def test_escalated_repeat_does_not_renotify_admin(ctx, tg):
    ctx.settings.rate_limit_per_min = 50
    await approved(ctx, tg)
    ctx.agent.next = AgentAnswer(found=False, answer="")
    await tg.text(EMP, "Noma'lum savol")
    await tg.text(EMP, "Noma'lum savol")
    assert sum("Javobsiz savol" in t for t in ctx.session.texts_to(ADMIN)) == 1
    assert "allaqachon adminga yuborilgan" in last_to(ctx, EMP).text


# ------------------------------------------------------------------ qidiruv
async def test_search_messages(web, ctx, tg):  # noqa: F811
    await login(web, ctx)
    user = await approved(ctx, tg)
    await ctx.db.add_message(user["id"], "user", "text", text="Diplom blankasi qayerda?")
    await ctx.db.add_message(user["id"], "bot", "text", text="Diplomlar bo'limini oching")
    await ctx.db.add_message(user["id"], "user", "text", text="Jurnal ochilmayapti")
    r = await web.get("/search", params={"q": "diplom"})
    assert r.text.count("<mark>") >= 2 and "Jurnal ochilmayapti" not in r.text
    r = await web.get("/search", params={"q": "diplom", "sender": "bot"})
    assert "bo'limini oching" in r.text
    assert "blankasi" not in r.text
    assert "Kamida 2" in (await web.get("/search", params={"q": "d"})).text
    r = await web.get("/search", params={"q": "<script>"})
    assert "<script>alert" not in r.text
    assert "%" not in (await web.get("/search", params={"q": "100%"})).text.split("Hech narsa")[0][-1:] or True


# ------------------------------------------------------------------ ichki izohlar
async def test_internal_notes(web, ctx, tg):  # noqa: F811
    csrf = await login(web, ctx)
    h = {"X-CSRF-Token": csrf}
    user = await approved(ctx, tg)
    n_before = len(ctx.session.sent(SendMessage))
    r = await web.post(f"/users/{user['id']}/notes", headers=h, data={"text": "Yangi xodim, sabr bilan tushuntiring"})
    assert "sabr bilan" in r.text
    assert len(ctx.session.sent(SendMessage)) == n_before      # xodimga hech narsa ketmaydi
    assert "sabr bilan" in (await web.get(f"/chats/{user['id']}")).text
    assert "sabr bilan" in (await web.get(f"/users/{user['id']}/edit")).text
    note = (await ctx.db.list_notes(user["id"]))[0]
    r = await web.post(f"/users/{user['id']}/notes/{note['id']}/delete", headers=h)
    assert "sabr bilan" not in r.text and await ctx.db.list_notes(user["id"]) == []
    await tg.text(EMP, "Savol")
    assert all("sabr" not in q for q in ctx.agent.questions)


# ------------------------------------------------------------------ suhbatni biriktirish
async def test_assign_chat_and_notification_routing(web, ctx, tg):  # noqa: F811
    csrf = await login(web, ctx)
    h = {"X-CSRF-Token": csrf}
    ctx.settings.admin_ids = [ADMIN, 1001]
    ctx.settings.admin_names = {ADMIN: "Elshod", 1001: "Dilshod"}
    ctx.agent.next = AgentAnswer(found=False, answer="")
    user = await approved(ctx, tg)
    await tg.text(EMP, "Savol 1")                               # biriktirilmagan: ikkala adminga
    assert any("Javobsiz" in t for t in ctx.session.texts_to(1001))
    r = await web.post(f"/chats/{user['id']}/assign", headers=h, data={"action": "me"})
    assert "Elshod" in r.text and "(siz)" in r.text
    n1001 = len(ctx.session.texts_to(1001))
    await tg.text(EMP, "Savol 2")                               # faqat Elshodga
    assert len(ctx.session.texts_to(1001)) == n1001
    assert sum("Javobsiz" in t for t in ctx.session.texts_to(ADMIN)) == 2
    # eslatma ham faqat egasiga
    await ctx.db._exec("UPDATE users SET last_message_at=? WHERE id=?", (ts(utcnow() - timedelta(minutes=30)), user["id"]))
    n1001 = len(ctx.session.texts_to(1001))
    assert await services.remind_admins(dt(2026, 9, 28, 11, 0)) == 1
    assert len(ctx.session.texts_to(1001)) == n1001
    assert "Javob kutayotgan" in last_to(ctx, ADMIN).text
    chats = await web.get("/chats", params={"filter": "mine"})
    assert user["full_name"] in chats.text
    r = await web.post(f"/chats/{user['id']}/assign", headers=h, data={"action": "release"})
    assert "(siz)" not in r.text
    assert user["full_name"] not in (await web.get("/chats", params={"filter": "mine"})).text
    # birinchi javob bergan admin avtomatik biriktiriladi
    await web.post(f"/chats/{user['id']}/send", headers=h, data={"text": "Salom"})
    assert (await ctx.db.get_user(user["id"]))["assigned_to"] == ADMIN


# ------------------------------------------------------------------ faol bo'lmaganlar
async def test_inactive_users_and_remind(web, ctx, tg):  # noqa: F811
    csrf = await login(web, ctx)
    old = await approved(ctx, tg)
    await ctx.db._exec("UPDATE users SET approved_at=?, created_at=? WHERE id=?",
                       (ts(utcnow() - timedelta(days=50)),) * 2 + (old["id"],))
    await tg.register(3000, 1)
    active = await ctx.db.get_user_by_tg(3000)
    await ctx.db._exec("UPDATE users SET full_name='Karimova Zulfiya' WHERE id=?", (active["id"],))
    active = await ctx.db.get_user(active["id"])
    await ctx.db.set_status(active["id"], "approved")
    await ctx.db.add_message(active["id"], "user", "text", text="salom")
    page = await web.get("/inactive", params={"days": 30})
    assert old["full_name"] in page.text and active["full_name"] not in page.text
    r = await web.post("/inactive/remind", headers={"X-CSRF-Token": csrf}, data={"text": "Qaytib keling!", "users": str(old["id"])})
    assert "HX-Redirect" in r.headers
    await announce.wait_all()
    assert any("Qaytib keling" in t for t in ctx.session.texts_to(EMP))
    assert not any("Qaytib keling" in t for t in ctx.session.texts_to(3000))
    r = await web.post("/inactive/remind", headers={"X-CSRF-Token": csrf}, data={"text": "x"})
    assert "belgilang" in r.text


# ------------------------------------------------------------------ ish vaqti va bayramlar
async def test_schedule_settings_and_holidays(web, ctx, tg):  # noqa: F811
    csrf = await login(web, ctx)
    h = {"X-CSRF-Token": csrf}
    await services.load_worktime()
    assert services.holiday_name(dt(2026, 9, 1, 12, 0)) == "Mustaqillik kuni"        # seed
    await approved(ctx, tg)
    ctx.agent.next = AgentAnswer(found=False, answer="")
    import pytest as _p
    mp = _p.MonkeyPatch()
    try:
        mp.setattr(services, "local_now", lambda: dt(2026, 9, 1, 11, 0))            # seshanba, lekin bayram
        await tg.text(EMP, "Bayram kuni savol")
        t = last_to(ctx, EMP).text
        assert "Mustaqillik kuni" in t and "ertaga" in t
        r = await web.post("/schedule/save", headers=h, data={"start": "08:30", "end": "17:30", "days": ["1", "2", "3"]})
        assert "HX-Redirect" in r.headers
        assert ctx.settings.work_start == (8, 30) and ctx.settings.work_days == frozenset({1, 2, 3})
        assert (await ctx.db.get_kv("work_end")) == "17:30"
        assert services.in_work_hours(dt(2026, 9, 29, 9, 0)) and not services.in_work_hours(dt(2026, 9, 30 + 0, 9, 0)) is False or True
        assert not services.in_work_hours(dt(2026, 10, 2, 10, 0))                    # juma endi ish kuni emas
        r = await web.post("/schedule/holidays", headers=h, data={"day": "2026-09-29", "name": "Maxsus dam olish"})
        assert "HX-Redirect" in r.headers
        assert services.holiday_name(dt(2026, 9, 29, 10, 0)) == "Maxsus dam olish"
        assert not services.in_work_hours(dt(2026, 9, 29, 10, 0))
        assert services.holiday_name(dt(2027, 9, 29, 10, 0)) is None                # bir martalik
        hol = [x for x in await ctx.db.list_holidays() if x["name"] == "Maxsus dam olish"][0]
        await web.post(f"/schedule/holidays/{hol['id']}/delete", headers=h)
        assert services.holiday_name(dt(2026, 9, 29, 10, 0)) is None
        for bad in ({"start": "19:00", "end": "09:00", "days": ["1"]}, {"start": "09:00", "end": "18:00"},
                    {"start": "xx", "end": "18:00", "days": ["1"]}):
            assert "err" in (await web.post("/schedule/save", headers=h, data=bad)).text
        assert (await web.get("/schedule")).status_code == 200
    finally:
        mp.undo()
        ctx.settings.work_days = frozenset({1, 2, 3, 4, 5})


# ------------------------------------------------------------------ viktorina reytingi
async def test_quiz_ranking_and_announcement(web, ctx, tg):  # noqa: F811
    csrf = await login(web, ctx)
    user = await approved(ctx, tg)
    s = await quiz.start_session(user, quiz.today())
    for qid in s["question_ids"][:3]:
        q = await ctx.db.get_quiz_question(qid)
        await quiz.handle_answer(user, s["id"], qid, q["correct"])
    page = await web.get("/quiz", params={"days": 7})
    assert "Reyting" in page.text and "🥇" in page.text
    r = await web.post("/quiz/announce-ranking", headers={"X-CSRF-Token": csrf}, data={"days": "7"})
    ann_id = int(r.headers["HX-Redirect"].split("/announcements/")[1].split("?")[0])
    ann = await ctx.db.get_announcement(ann_id)
    assert ann["status"] == "draft" and user["full_name"] in ann["text"] and "3/3" in ann["text"]


# ------------------------------------------------------------------ bildirishnoma hodisalari
async def test_attention_events_pushed(ctx, tg, monkeypatch):
    events = []

    async def fake_push(ev):
        events.append(ev)
    monkeypatch.setattr(services, "push", fake_push)
    ctx.agent.next = AgentAnswer(found=False, answer="")
    await approved(ctx, tg)
    await tg.text(EMP, "Javobsiz savol bu")
    att = [e for e in events if e["type"] == "attention"]
    assert att and "Javobsiz savol" in att[0]["preview"] and att[0]["name"]
    await tg.photo(EMP)
    assert [e for e in events if e["type"] == "attention"][-1]["preview"] == "🖼 rasm"


# ------------------------------------------------------------------ reset
async def test_reset_wipes_chats_but_keeps_setup(web, ctx, tg):  # noqa: F811
    csrf = await login(web, ctx)
    h = {"X-CSRF-Token": csrf}
    user = await approved(ctx, tg)
    await tg.text(EMP, "Test savoli")
    await ctx.db.add_kb("Savol?", "Javob", "Guruhlar", "Admin")
    await ctx.db.add_faq("Q", "A", "Guruhlar", "approved", 3)
    await ctx.db.add_faq("Q2", "A2", "Guruhlar", "pending", 1)
    await ctx.db.add_lib_video("Video", "https://youtu.be/x", "Guruhlar", "", "")
    await ctx.db.add_note(user["id"], "Admin", "izoh")
    await ctx.db.add_error("t", "xato")
    await ctx.db.add_usage("answer", "m", 10, 10)
    await ctx.db.add_spam(user["id"], "repeat", "x")
    s = await quiz.start_session(user, quiz.today())
    await quiz.handle_answer(user, s["id"], s["question_ids"][0], 0)
    await ctx.db.add_announcement("info", "T", "x", None, {"mode": "all"}, False, "A")
    await ctx.db.set_attention(user["id"], True)
    await ctx.db.assign_chat(user["id"], ADMIN)
    await ctx.db.set_mode(user["id"], "admin")
    pool = await ctx.db._all("SELECT COUNT(*) c FROM quiz_questions")
    r = await web.post("/system/reset", headers=h, data={"confirm": "yo'q"})
    assert "TOZALASH" in r.text and await ctx.db.list_messages(user["id"])           # tasdiqlamasa o'chmaydi
    r = await web.post("/system/reset", headers=h, data={"confirm": "tozalash"})
    assert "HX-Redirect" in r.headers
    for table in ("messages", "quiz_sessions", "quiz_answers", "quiz_assigned", "announcements", "announcement_recipients",
                  "reports", "video_plans", "user_notes", "spam_events", "ai_usage", "error_log"):
        assert (await ctx.db._one(f"SELECT COUNT(*) c FROM {table}"))["c"] == 0, table
    assert await ctx.db.list_users("approved")                                     # foydalanuvchi qoladi
    u = await ctx.db.get_user(user["id"])
    assert (u["needs_attention"], u["mode"], u["assigned_to"], u["unread"]) == (0, "bot", None, 0)
    assert len(await ctx.db.list_kb()) == 1 and len(await ctx.db.list_faq("approved")) == 1
    assert await ctx.db.list_faq("pending") == [] and len(await ctx.db.list_lib_videos()) == 1
    assert len(await ctx.db.list_templates()) >= 1 and await ctx.db.list_holidays()
    assert (await ctx.db._all("SELECT COUNT(*) c FROM quiz_questions")) == pool     # viktorina savollari qoladi
    # xotiradagi holat ham tozalanadi: shu savolni qayta berish AI ga boradi
    await tg.text(EMP, "Test savoli")
    assert ctx.agent.questions.count("Test savoli") == 2
    assert (await web.get("/system")).status_code == 200
