"""Yangi imkoniyatlar: bilimlar bazasi, FAQ, video kutubxona, viktorina, eslatmalar, ish vaqti, shablonlar."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from aiogram.methods import SendMessage

from app import faq as faq_mod
from app import quiz, services
from app.agent import AgentAnswer
from app.bot.keyboards import BTN_FAQ, BTN_QUIZ, BTN_VIDEO
from app.db import ts, utcnow
from tests.conftest import ADMIN, EMP
from tests.test_web import login, make_user, web  # noqa: F401

TZ = ZoneInfo("Asia/Tashkent")


def dt(y, m, d, h, mi):
    return datetime(y, m, d, h, mi, tzinfo=TZ)


def last_to(ctx, chat_id):
    return [c for c in ctx.session.sent(SendMessage) if c.chat_id == chat_id][-1]


async def approved(ctx, tg, role_idx=0):
    await tg.register(role_idx=role_idx)
    user = await ctx.db.get_user_by_tg(EMP)
    await ctx.db.set_status(user["id"], "approved")
    return await ctx.db.get_user(user["id"])


# ------------------------------------------------------------------ bilimlar bazasi
async def test_kb_add_and_used_by_agent(web, ctx, tg):
    csrf = await login(web, ctx)
    h = {"X-CSRF-Token": csrf}
    r = await web.post("/kb/save", headers=h, data={
        "question": "Diplom blankasi raqamini qayerdan topaman? PINFL 51805055530014",
        "answer": "Diplomlar bo'limida blanka raqami ko'rsatilgan.", "topic": "Diplomlar", "also_faq": "1"})
    assert r.headers["hx-redirect"].startswith("/kb?notice=")
    entries = await ctx.db.list_kb()
    assert len(entries) == 1 and "51805055530014" not in entries[0]["question"]
    assert len(await ctx.db.list_faq("approved")) == 1

    await approved(ctx, tg)
    await tg.text(EMP, "Diplom blankasi raqami qayerda?")
    assert ctx.agent.kb_seen and ctx.agent.kb_seen[0]["id"] == entries[0]["id"]
    await tg.text(EMP, "Jurnalga baho qo'yish")
    assert not ctx.agent.kb_seen  # mos kelmagan savolga bilim qo'shilmaydi


async def test_kb_prefill_from_admin_message(web, ctx, tg):
    csrf = await login(web, ctx)
    user = await make_user(ctx, tg)
    await ctx.db.add_message(user["id"], "user", "text", text="Buyruqni qanday bekor qilaman?")
    mid = await ctx.db.add_message(user["id"], "admin", "text", text="Buyruq sahifasida Bekor qilish tugmasini bosing.")
    r = await web.get(f"/kb?msg={mid}")
    assert "Buyruqni qanday bekor qilaman?" in r.text and "Bekor qilish tugmasini bosing" in r.text


async def test_kb_validation(web, ctx):
    csrf = await login(web, ctx)
    r = await web.post("/kb/save", headers={"X-CSRF-Token": csrf}, data={"question": "a", "answer": "b"})
    assert "kamida 5" in r.text


def test_find_relevant():
    from app.kb import find_relevant

    entries = [{"id": 1, "question": "Diplom blankasi raqamini qayerdan topaman?", "answer": "x"},
               {"id": 2, "question": "Dars jadvali qanday tuziladi?", "answer": "y"}]
    assert [e["id"] for e in find_relevant(entries, "diplom blankasi raqami qayerda")] == [1]
    assert find_relevant(entries, "Umuman boshqa narsa haqida") == []


# ------------------------------------------------------------------ FAQ
async def test_faq_analysis_and_bot_menu(web, ctx, tg):
    user = await approved(ctx, tg)
    for i in range(5):
        await ctx.db.add_message(user["id"], "user", "text", text=f"Guruhga o'quvchi qo'shish {i}", topic="Guruhlar", found=True)
        await ctx.db.add_message(user["id"], "bot", "text", text="1. Guruhlar menyusi", topic="Guruhlar", found=True)
    ctx.agent.faq_result = [{"question": "O'quvchini guruhga qanday qo'shaman?", "answer": "1. **Guruhlar** menyusi.",
                             "topic": "Guruhlar", "count": 5, "match_id": None}]
    res = await faq_mod.analyze(notify=True)
    assert res["created"] == 1
    assert any("FAQ uchun 1 ta" in t for t in ctx.session.texts_to(ADMIN))
    pending = await ctx.db.list_faq("pending")
    assert len(pending) == 1 and pending[0]["ask_count"] == 5
    # qayta tahlil takror yaratmaydi
    assert (await faq_mod.analyze(notify=False))["created"] == 0

    # bot menyusida hali ko'rinmaydi
    await tg.text(EMP, BTN_FAQ)
    assert "tayyor ro'yxat yo'q" in last_to(ctx, EMP).text

    csrf = await login(web, ctx)
    await web.post(f"/faq/{pending[0]['id']}/status", headers={"X-CSRF-Token": csrf}, data={"status": "approved"})
    await tg.text(EMP, BTN_FAQ)
    kb = last_to(ctx, EMP).reply_markup.inline_keyboard
    assert kb[0][0].callback_data.startswith("faqt:")
    await tg.callback(EMP, kb[0][0].callback_data)
    await tg.callback(EMP, f"faqq:{pending[0]['id']}")
    out = last_to(ctx, EMP)
    assert "qanday qo'shaman" in out.text and "<b>Guruhlar</b>" in out.text
    assert (await ctx.db.get_faq(pending[0]["id"]))["views"] == 1


async def test_faq_too_few_questions(ctx):
    assert (await faq_mod.analyze())["reason"] == "few"


# ------------------------------------------------------------------ video kutubxona
async def test_video_library_and_attach(web, ctx, tg):
    csrf = await login(web, ctx)
    h = {"X-CSRF-Token": csrf}
    bad = await web.post("/library/save", headers=h, data={"title": "Rolik", "url": "javascript:alert(1)"})
    assert "http" in bad.text
    ok = await web.post("/library/save", headers=h, data={
        "title": "Jurnal bilan ishlash", "url": "https://youtu.be/abc123", "topic": "Elektron jurnal",
        "keywords": "baho, jurnal"})
    assert ok.headers["hx-redirect"].startswith("/library")
    vid = (await ctx.db.list_lib_videos())[0]

    await approved(ctx, tg)
    ctx.agent.next = AgentAnswer(found=True, answer="1. Jurnalni oching.", topic="Elektron jurnal", title="Baho qo'yish",
                                 section="O'qituvchi qo'llanmasi, 5", video_id=vid["id"])
    await tg.text(EMP, "Baho qanday qo'yiladi?")
    assert ctx.agent.videos_seen and ctx.agent.videos_seen[0]["id"] == vid["id"]
    sent = last_to(ctx, EMP)
    assert 'href="https://youtu.be/abc123"' in sent.text and "Jurnal bilan ishlash" in sent.text
    assert (await ctx.db.get_lib_video(vid["id"]))["views"] == 1

    await tg.text(EMP, BTN_VIDEO)
    kb = last_to(ctx, EMP).reply_markup.inline_keyboard
    await tg.callback(EMP, kb[0][0].callback_data)
    assert "youtu.be/abc123" in last_to(ctx, EMP).text


async def test_agent_ignores_unknown_video_id():
    from types import SimpleNamespace

    from app.agent import TexnikumAgent
    from app.config import Settings

    class Fake(TexnikumAgent):
        def __init__(self):
            self.s = Settings(openai_api_key="k", vector_store_id="v")
            self.client = SimpleNamespace(_is_fake=True)

        async def _call(self, **kw):
            return '{"found": true, "answer": "Ha", "topic": "Boshqa", "video_id": 999}', [], 1, 1

    res = await Fake().answer("savol", None, [], videos=[{"id": 1, "title": "x", "url": "u"}])
    assert res.video_id is None


# ------------------------------------------------------------------ ish vaqti va eslatmalar
async def test_availability_messages(ctx, tg, monkeypatch):
    await approved(ctx, tg)
    ctx.agent.next = AgentAnswer(found=False, answer="")
    monkeypatch.setattr(services, "local_now", lambda: dt(2026, 9, 28, 11, 0))  # dushanba 11:00
    await tg.text(EMP, "Noma'lum savol")
    assert "Admin ish vaqtida" in last_to(ctx, EMP).text
    monkeypatch.setattr(services, "local_now", lambda: dt(2026, 9, 26, 15, 0))  # shanba
    await tg.text(EMP, "Yana noma'lum savol")
    t = last_to(ctx, EMP).text
    assert "dam olish kuni" in t and "dushanba" in t
    monkeypatch.setattr(services, "local_now", lambda: dt(2026, 9, 29, 21, 0))  # seshanba 21:00
    await tg.text(EMP, "Uchinchi noma'lum savol")
    t = last_to(ctx, EMP).text
    assert "ish vaqtidan tashqari" in t and "09:00–19:00" in t and "ertaga" in t
    # adminga har doim darhol xabar boradi
    assert sum("Javobsiz savol" in x for x in ctx.session.texts_to(ADMIN)) == 3


async def test_reminders(ctx, tg):
    user = await approved(ctx, tg)
    await ctx.db.add_message(user["id"], "user", "text", text="Yordam kerak")
    await ctx.db.set_attention(user["id"], True)
    old = (utcnow() - timedelta(minutes=25)).strftime("%Y-%m-%d %H:%M:%S")
    await ctx.db._exec("UPDATE users SET last_message_at=? WHERE id=?", (old, user["id"]))

    assert await services.remind_admins(dt(2026, 9, 28, 23, 0)) == 0        # 22:00 dan keyin yubormaydi
    assert await services.remind_admins(dt(2026, 9, 28, 7, 0)) == 0         # 08:00 dan oldin yubormaydi
    n = len(ctx.session.texts_to(ADMIN))
    assert await services.remind_admins(dt(2026, 9, 28, 8, 0)) == 1
    txt = ctx.session.texts_to(ADMIN)[n]
    assert "Javob kutayotgan suhbatlar: 1" in txt and "Yordam kerak" in txt
    # admin javob yozgach eslatma to'xtaydi
    await services.admin_send(user["id"], "Javob", ADMIN)
    assert await services.remind_admins(dt(2026, 9, 28, 12, 0)) == 0


async def test_recent_waiting_not_reminded_yet(ctx, tg):
    user = await approved(ctx, tg)
    await ctx.db.add_message(user["id"], "user", "text", text="Yangi")
    await ctx.db.set_attention(user["id"], True)
    assert await services.remind_admins(dt(2026, 9, 28, 12, 0)) == 0


# ------------------------------------------------------------------ viktorina
def _kb_of(ctx):
    return last_to(ctx, EMP).reply_markup.inline_keyboard[0]


async def test_quiz_full_flow(ctx, tg):
    user = await approved(ctx, tg, role_idx=1)  # O'quv bo'limi
    await tg.text(EMP, BTN_QUIZ)
    first = last_to(ctx, EMP)
    assert "Kunlik test" in first.text and "1/5" in first.text and first.parse_mode == "HTML"
    session = await ctx.db.get_quiz_session(user["id"], quiz.today())
    assert len(session["question_ids"]) == 5

    results = []
    for step in range(5):
        row = _kb_of(ctx)
        qid = session["question_ids"][step]
        q = await ctx.db.get_quiz_question(qid)
        wrong = (q["correct"] + 1) % 3
        pick = q["correct"] if step % 2 == 0 else wrong
        await tg.callback(EMP, f"qz:{session['id']}:{qid}:{pick}")
        results.append(pick == q["correct"])
        if step % 2 == 1:
            # noto'g'ri javobda to'g'ri javob ko'rsatiladi (tahrirlangan xabar)
            edit = [c for c in ctx.session.calls if c.__class__.__name__ == "EditMessageText"][-1]
            assert "noto'g'ri javob berdingiz" in edit.text and "To'g'ri javob" in edit.text
        else:
            edit = [c for c in ctx.session.calls if c.__class__.__name__ == "EditMessageText"][-1]
            assert "to'g'ri javob berdingiz" in edit.text and "noto'g'ri" not in edit.text
    assert "Test yakunlandi" in last_to(ctx, EMP).text and "3/5" in last_to(ctx, EMP).text
    done = await ctx.db.get_quiz_session(user["id"], quiz.today())
    assert done["status"] == "done" and done["score"] == 3

    # ikkinchi marta bosish hisobga olinmaydi
    before = len(ctx.session.calls)
    await tg.callback(EMP, f"qz:{session['id']}:{session['question_ids'][0]}:0")
    assert (await ctx.db.get_quiz_session(user["id"], quiz.today()))["score"] == 3
    await tg.text(EMP, BTN_QUIZ)
    assert "yakunlangan" in last_to(ctx, EMP).text and "3/5" in last_to(ctx, EMP).text


async def test_quiz_questions_never_repeat_and_are_role_based(ctx, tg):
    user = await approved(ctx, tg, role_idx=3)  # Buxgalter
    seen: set[int] = set()
    for day in ("2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"):
        s = await quiz.start_session(user, day)
        ids = set(s["question_ids"])
        assert len(ids) == 5 and not ids & seen
        seen |= ids
    roles = {(await ctx.db.get_quiz_question(i))["role"] for i in seen}
    assert roles == {"Buxgalter"}
    assert ctx.agent.quiz_calls >= 2  # zaxira tugagach yangi savollar tuzildi


async def test_quiz_options_are_three_and_correct_valid(ctx):
    n = await ctx.db.add_quiz_questions("Buxgalter", [
        {"question": "Q1?", "options": ["a", "b", "c"], "correct": 1},
        {"question": "Q2?", "options": ["a", "b"], "correct": 0},          # 2 variant: rad
        {"question": "Q3?", "options": ["a", "a", "c"], "correct": 0},     # takror variant: rad
        {"question": "Q1?", "options": ["x", "y", "z"], "correct": 0},     # takror savol: rad
    ])
    assert n == 1
    q = (await ctx.db._all("SELECT id FROM quiz_questions"))[0]
    full = await ctx.db.get_quiz_question(q["id"])
    assert len(full["options"]) == 3 and full["options"][full["correct"]] == "b"


async def test_quiz_tick_window_and_spread(ctx, tg):
    for uid in (2001, 2002, 2003, 2004):
        await tg.register(uid=uid, role_idx=0)
        u = await ctx.db.get_user_by_tg(uid)
        await ctx.db.set_status(u["id"], "approved")
    assert await quiz.tick(dt(2026, 9, 28, 12, 0)) == 0      # oynadan oldin
    assert await quiz.tick(dt(2026, 9, 28, 13, 30)) == 0     # oynadan keyin
    first = await quiz.tick(dt(2026, 9, 28, 12, 20))
    assert 0 < first < 4                                    # hammasiga birdan emas, bir tekis
    total = first
    for m in range(22, 60, 2):
        total += await quiz.tick(dt(2026, 9, 28, 12, m))
    total += await quiz.tick(dt(2026, 9, 28, 13, 0))
    assert total == 4
    assert await quiz.tick(dt(2026, 9, 28, 12, 58)) == 0     # hamma olgan


async def test_quiz_skips_admin_and_pending(ctx, tg):
    await tg.text(ADMIN, "/start")  # Administrator roli
    await tg.register()             # pending
    assert await quiz.tick(dt(2026, 9, 28, 12, 20)) == 0


async def test_quiz_pages(web, ctx, tg):
    await approved(ctx, tg)
    csrf = await login(web, ctx)
    await tg.text(EMP, BTN_QUIZ)
    r = await web.get("/quiz?days=7")
    assert r.status_code == 200 and "Kunlik test" in r.text and "Valiyev Ali" in r.text
    r = await web.post("/quiz/prepare", headers={"X-CSRF-Token": csrf})
    assert r.headers["hx-redirect"].startswith("/quiz")


# ------------------------------------------------------------------ shablonlar, foydalanuvchini tahrirlash, admin nomi
async def test_templates_crud_and_chat_select(web, ctx, tg):
    csrf = await login(web, ctx)
    h = {"X-CSRF-Token": csrf}
    assert len(await ctx.db.list_templates()) >= 5  # boshlang'ich shablonlar
    await web.post("/templates/save", headers=h, data={"title": "Yangi", "text": "Salom, {ism}!"})
    tpl = [t for t in await ctx.db.list_templates() if t["title"] == "Yangi"][0]
    user = await make_user(ctx, tg)
    await ctx.db.add_message(user["id"], "user", "text", text="Salom")
    page = await web.get(f"/chats/{user['id']}")
    assert "Salom, {ism}!" in page.text and 'id="tpl"' in page.text
    await web.post(f"/templates/{tpl['id']}/delete", headers=h)
    assert not [t for t in await ctx.db.list_templates() if t["title"] == "Yangi"]


async def test_user_edit(web, ctx, tg):
    csrf = await login(web, ctx)
    h = {"X-CSRF-Token": csrf}
    user = await make_user(ctx, tg, approve=False)
    assert "Tahrirlash" in (await web.get("/users")).text
    assert (await web.get(f"/users/{user['id']}/edit")).status_code == 200
    r = await web.post(f"/users/{user['id']}/edit", headers=h, data={
        "full_name": "Karimov Vali Aliyevich", "phone": "90 123 45 67", "tech_name": "Chirchiq texnikumi",
        "role": "Buxgalter", "status": "approved"})
    assert r.headers["hx-redirect"].startswith("/users")
    u = await ctx.db.get_user(user["id"])
    assert (u["full_name"], u["phone"], u["tech_name"], u["role"], u["status"]) == (
        "Karimov Vali Aliyevich", "+901234567", "Chirchiq texnikumi", "Buxgalter", "approved")
    assert any("ruxsat berildi" in t.lower() for t in ctx.session.texts_to(EMP))
    bad = await web.post(f"/users/{user['id']}/edit", headers=h, data={"full_name": "Ab", "phone": "", "role": ""})
    assert "juda qisqa" in bad.text
    bad = await web.post(f"/users/{user['id']}/edit", headers=h, data={"full_name": "Valid Name", "phone": "12"})
    assert "noto'g'ri" in bad.text


async def test_admin_name_shown(web, ctx, tg):
    ctx.settings.admin_names = {ADMIN: "Elshod Karimov"}
    csrf = await login(web, ctx)
    user = await make_user(ctx, tg)
    await web.post(f"/chats/{user['id']}/send", data={"text": "Salom"}, headers={"X-CSRF-Token": csrf})
    assert any("Elshod Karimov" in t for t in ctx.session.texts_to(EMP))
    msgs = [m for m in await ctx.db.list_messages(user["id"]) if m["sender"] == "admin"]
    assert msgs[0]["author"] == "Elshod Karimov"
    page = await web.get(f"/chats/{user['id']}")
    assert "Admin: Elshod Karimov" in page.text and "Bilimlar bazasiga qo" in page.text


async def test_all_new_pages_render(web, ctx, tg):
    await login(web, ctx)
    for path in ("/kb", "/faq", "/faq?status=approved", "/faq?status=hidden", "/library", "/templates", "/quiz", "/"):
        r = await web.get(path)
        assert r.status_code == 200, path


# ------------------------------------------------------------------ OpenAI vector store sinxronlash
async def test_kb_sync_replaces_file(ctx):
    from types import SimpleNamespace

    from app import kb as kb_mod

    calls = []

    class Files:
        n = 0

        async def create(self, **kw):
            Files.n += 1
            calls.append(("upload", kw["file"][0]))
            return SimpleNamespace(id=f"file_{Files.n}")

        async def delete(self, fid):
            calls.append(("del_file", fid))

    class VSFiles:
        async def create_and_poll(self, **kw):
            calls.append(("attach", kw["vector_store_id"], kw["file_id"]))

        async def delete(self, fid, **kw):
            calls.append(("detach", fid))

    ctx.agent.client = SimpleNamespace(files=Files(), vector_stores=SimpleNamespace(files=VSFiles()))
    await ctx.db.add_kb("Savol bir?", "Javob bir.", "Boshqa")
    assert await kb_mod.sync_to_vector_store() == "ok"
    assert ("attach", "vs_test", "file_1") in calls
    assert await kb_mod.sync_to_vector_store() == "ok" and Files.n == 1   # o'zgarish yo'q: qayta yuklanmaydi
    await ctx.db.add_kb("Savol ikki?", "Javob ikki.", "Boshqa")
    assert await kb_mod.sync_to_vector_store() == "ok"
    assert ("detach", "file_1") in calls and ("del_file", "file_1") in calls and ("attach", "vs_test", "file_2") in calls

    class Boom(Files):
        async def create(self, **kw):
            raise RuntimeError("tarmoq xatosi")

    ctx.agent.client = SimpleNamespace(files=Boom(), vector_stores=SimpleNamespace(files=VSFiles()))
    await ctx.db.add_kb("Savol uch?", "Javob uch.", "Boshqa")
    assert "tarmoq xatosi" in await kb_mod.sync_to_vector_store()
    assert "tarmoq xatosi" in (await ctx.db.get_kv("kb_sync_error"))
