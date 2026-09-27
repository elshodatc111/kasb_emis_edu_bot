from __future__ import annotations

from aiogram.methods import SendMessage

from app.agent import AgentAnswer, AgentError
from tests.conftest import ADMIN, EMP


async def test_registration_and_approval(ctx, tg):
    await tg.register()
    user = await ctx.db.get_user_by_tg(EMP)
    assert user["status"] == "pending"
    assert user["full_name"] == "Valiyev Ali Karimovich"
    assert user["phone"] == "+998901234567"
    assert user["tech_name"] == "Toshkent transport texnikumi"
    assert user["role"] == "O'qituvchi"
    # admin ga so'rov tushdi (tugmalar bilan)
    admin_msgs = [c for c in ctx.session.sent(SendMessage) if c.chat_id == ADMIN]
    assert admin_msgs and "Yangi foydalanish so'rovi" in admin_msgs[0].text
    assert admin_msgs[0].reply_markup is not None

    # ruxsatsiz foydalanuvchi savol bersa AI ishlamaydi
    await tg.text(EMP, "Jurnalga baho qanday qo'yiladi?")
    assert ctx.agent.questions == []
    assert any("ko'rib chiqilmoqda" in t for t in ctx.session.texts_to(EMP))

    # ruxsatsiz rasm ham saqlanmaydi
    await tg.photo(EMP)
    assert await ctx.db.list_messages(user["id"]) == []

    # admin tugma orqali ruxsat beradi (begona odam bera olmaydi)
    await tg.callback(EMP, f"appr:{user['id']}")
    assert (await ctx.db.get_user(user["id"]))["status"] == "pending"
    await tg.callback(ADMIN, f"appr:{user['id']}")
    assert (await ctx.db.get_user(user["id"]))["status"] == "approved"
    assert any("ruxsat berildi" in t for t in ctx.session.texts_to(EMP))


async def _approved(ctx, tg):
    await tg.register()
    user = await ctx.db.get_user_by_tg(EMP)
    await tg.callback(ADMIN, f"appr:{user['id']}")
    return await ctx.db.get_user(user["id"])


async def test_answer_flow_formatted(ctx, tg):
    user = await _approved(ctx, tg)
    await tg.text(EMP, "Jurnalga baho qanday qo'yiladi?")
    assert ctx.agent.questions == ["Jurnalga baho qanday qo'yiladi?"]
    msgs = await ctx.db.list_messages(user["id"])
    assert [m["sender"] for m in msgs] == ["user", "bot"]
    assert msgs[0]["topic"] == "Elektron jurnal" and msgs[0]["found"] == 1
    assert "Manba: O'qituvchi qo'llanmasi, 5" in msgs[1]["text"]
    assert msgs[1]["tokens_in"] == 100
    last = ctx.session.sent(SendMessage)[-1]
    assert last.reply_markup is None  # Foydali/Foydasiz tugmalari yo'q
    assert last.parse_mode == "HTML"
    assert "AI Menejer" in last.text and "Manba: O'qituvchi qo'llanmasi, 5" in last.text
    assert "filecite" not in last.text


async def test_clean_citations_and_html():
    from app.format import bot_html, clean_citations
    dirty = "Matn.\ue200filecite\ue202turn3file7\ue202turn3file6\ue201 Oxiri"
    assert clean_citations(dirty) == "Matn. Oxiri"


async def test_bullet_dashes_and_real_hyphens_preserved():
    """Ro'yxat uchun "- band" ▫️ ga aylanadi, lekin so'z ichidagi va telefon raqamidagi chiziqcha o'chib ketmasligi kerak."""
    from app.format import bot_html
    body = "- Eslatma: PINFL yopiladi\nTelefon: +998-90-123-45-67, ko'p-tarmoqli tizim"
    html_out = bot_html("", body)
    assert "▫️ Eslatma: PINFL yopiladi" in html_out
    assert "+998-90-123-45-67" in html_out and "ko'p-tarmoqli" in html_out
    out = bot_html("Sarlavha", "1. **Menyu** ni oching <b>x</b>\n2. Saqlang", "Qo'llanma, 1.1")
    assert "<b>1.</b> <b>Menyu</b>" in out and "&lt;b&gt;x&lt;/b&gt;" in out


async def test_pinfl_masked_before_openai(ctx, tg):
    user = await _approved(ctx, tg)
    await tg.text(EMP, "51805055530014 PINFL li o'quvchi topilmadi, pasport AE2744857")
    sent_to_ai = ctx.agent.questions[0]
    assert "51805055530014" not in sent_to_ai and "AE2744857" not in sent_to_ai
    assert "[PINFL]" in sent_to_ai and "[PASPORT]" in sent_to_ai
    # chat tarixida asl matn qoladi (admin ko'radi)
    msgs = await ctx.db.list_messages(user["id"])
    assert "51805055530014" in msgs[0]["text"]
    # keyingi savolda tarix ham tozalangan holda ketadi
    await tg.text(EMP, "Yana bir savol")
    for h in ctx.agent.histories[-1]:
        assert "51805055530014" not in h["text"] and "AE2744857" not in h["text"]


async def test_not_found_escalates_to_admin(ctx, tg):
    user = await _approved(ctx, tg)
    ctx.agent.next = AgentAnswer(found=False, answer="", topic="Diplomlar")
    await tg.text(EMP, "Diplom raqami qayerdan olinadi?")
    u = await ctx.db.get_user(user["id"])
    assert u["needs_attention"] == 1
    assert any("adminga yuborildi" in t for t in ctx.session.texts_to(EMP))
    assert any("Javobsiz savol" in t for t in ctx.session.texts_to(ADMIN))
    msgs = await ctx.db.list_messages(user["id"])
    assert msgs[0]["found"] == 0 and msgs[0]["topic"] == "Diplomlar"


async def test_openai_error_escalates(ctx, tg):
    user = await _approved(ctx, tg)
    ctx.agent.next = AgentError("timeout")
    await tg.text(EMP, "Savol")
    assert (await ctx.db.get_user(user["id"]))["needs_attention"] == 1
    assert any("Javobsiz savol" in t for t in ctx.session.texts_to(ADMIN))


async def test_photo_is_stored_but_never_answered_or_sent_to_ai(ctx, tg):
    user = await _approved(ctx, tg)
    before = len(ctx.session.texts_to(EMP))
    await tg.photo(EMP, caption="Mana xato")
    assert ctx.agent.questions == []                         # OpenAI ga ketmadi
    assert len(ctx.session.texts_to(EMP)) == before           # bot javob bermadi
    msgs = await ctx.db.list_messages(user["id"])
    assert msgs[-1]["kind"] == "photo" and msgs[-1]["file_id"] == "PHOTO_FILE" and msgs[-1]["text"] == "Mana xato"
    assert (await ctx.db.get_user(user["id"]))["needs_attention"] == 1
    assert any("Rasm keldi" in t for t in ctx.session.texts_to(ADMIN))
    # ketma-ket rasmlar (albom) adminni spam qilmaydi
    n_admin = len([t for t in ctx.session.texts_to(ADMIN) if "Rasm keldi" in t])
    await tg.photo(EMP)
    await tg.photo(EMP)
    assert len([t for t in ctx.session.texts_to(ADMIN) if "Rasm keldi" in t]) == n_admin
    assert len(await ctx.db.list_messages(user["id"])) == 3
    # rasm faylini yuklab olish ham so'ralmadi
    from aiogram.methods import GetFile
    assert ctx.session.sent(GetFile) == []


async def test_other_media_rejected(ctx, tg):
    from aiogram.types import Voice

    user = await _approved(ctx, tg)
    await tg.send(EMP, voice=Voice(file_id="v", file_unique_id="v", duration=3))
    assert any("Faqat matn va rasm qabul qilinadi" in t for t in ctx.session.texts_to(EMP))
    assert ctx.agent.questions == []
    msgs = await ctx.db.list_messages(user["id"])
    assert msgs[-1]["kind"] == "other" and msgs[-1]["file_id"] is None


async def test_admin_takeover_mode_pauses_ai(ctx, tg):
    user = await _approved(ctx, tg)
    await tg.text(EMP, "/admin")
    u = await ctx.db.get_user(user["id"])
    assert u["mode"] == "admin" and u["needs_attention"] == 1
    assert any("Adminga murojaat" in t for t in ctx.session.texts_to(ADMIN))
    await tg.text(EMP, "Salom admin")
    assert ctx.agent.questions == []                          # AI jim
    await tg.text(EMP, "/bot")
    assert (await ctx.db.get_user(user["id"]))["mode"] == "bot"
    await tg.text(EMP, "Endi botdan so'rayman")
    assert len(ctx.agent.questions) == 1


async def test_admin_mode_expires(ctx, tg):
    from datetime import timedelta

    from app.db import ts, utcnow

    user = await _approved(ctx, tg)
    await ctx.db.set_mode(user["id"], "admin")
    await ctx.db._exec("UPDATE users SET mode_since=? WHERE id=?", (ts(utcnow() - timedelta(minutes=200)), user["id"]))
    await tg.text(EMP, "Savol")
    assert len(ctx.agent.questions) == 1
    assert (await ctx.db.get_user(user["id"]))["mode"] == "bot"


async def test_rate_limit(ctx, tg):
    await _approved(ctx, tg)
    for i in range(5):
        await tg.text(EMP, f"Savol {i}")
    assert len(ctx.agent.questions) == 3                      # rate_limit_per_min=3
    assert any("Juda ko'p savol" in t for t in ctx.session.texts_to(EMP))


async def test_admin_start_autoapproved(ctx, tg):
    await tg.text(ADMIN, "/start")
    u = await ctx.db.get_user_by_tg(ADMIN)
    assert u["status"] == "approved" and u["role"] == "Administrator"


async def test_blocked_user_ignored(ctx, tg):
    user = await _approved(ctx, tg)
    await ctx.db.set_status(user["id"], "blocked")
    before = len(ctx.session.calls)
    await tg.text(EMP, "Salom")
    await tg.photo(EMP)
    assert len(ctx.session.calls) == before and ctx.agent.questions == []


async def test_rejected_can_reapply(ctx, tg):
    await tg.register()
    user = await ctx.db.get_user_by_tg(EMP)
    await tg.callback(ADMIN, f"rej:{user['id']}")
    assert (await ctx.db.get_user(user["id"]))["status"] == "rejected"
    await tg.register()
    assert (await ctx.db.get_user(user["id"]))["status"] == "pending"


async def test_registration_validation(ctx, tg):
    await tg.text(EMP, "/start")
    await tg.text(EMP, "Ali")            # juda qisqa
    await tg.text(EMP, "Ali Valiyev")
    await tg.text(EMP, "123")            # noto'g'ri telefon
    texts = ctx.session.texts_to(EMP)
    assert any("to'liq yozing" in t for t in texts) and any("noto'g'ri" in t for t in texts)
    assert await ctx.db.get_user_by_tg(EMP) is None
