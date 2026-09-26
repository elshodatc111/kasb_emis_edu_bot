from __future__ import annotations

import logging
import re
import time
from collections import defaultdict, deque

from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.chat_action import ChatActionSender

from .. import kb as kb_mod
from .. import announce, quiz, services
from ..agent import AgentError
from ..constants import ROLES, TOPICS
from ..context import get_ctx
from ..db import parse_ts, utcnow
from ..privacy import mask_sensitive
from ..format import bot_html, bot_plain, system_html
from .keyboards import (LBL_ADMIN, LBL_BOT, LBL_FAQ, LBL_HELP, LBL_QUIZ, LBL_VIDEO, approval_keyboard, is_button, main_menu, phone_keyboard,
                        roles_keyboard)

log = logging.getLogger(__name__)
router = Router(name="main")

_rate: dict[int, deque] = defaultdict(deque)

HELP_TEXT = (
    "🎓 Men Prof ta'lim tizimi bo'yicha savollaringizga qo'llanmalar asosida javob beraman.\n\n"
    "✍️ Savolingizni matn ko'rinishida yozing.\n"
    "🖼 Rasm (skrinshot) yuborishingiz mumkin, lekin bot rasmni ko'rmaydi va tahlil qilmaydi, u faqat adminga ko'rinadi. "
    "Iltimos, rasmda shaxsiy ma'lumotlarni (PINFL, pasport) yopib yuboring.\n"
    "🚫 Audio, video va fayllar qabul qilinmaydi.\n"
    "👥 Boshqa lavozimdagi hamkasblaringiz uchun ham savol berishingiz mumkin.\n"
    "❓ \"Ko'p so'raladigan savollar\" va 🎬 \"Video darslar\" tayyor javoblar va o'quv videolarini ko'rsatadi.\n"
    "🧩 \"Kunlik test\" orqali har kuni 5 ta savolga javob berib bilimingizni sinang.\n"
    "🙋 Admin bilan gaplashish uchun \"Adminga murojaat\" tugmasini bosing."
)


class Reg(StatesGroup):
    name = State()
    phone = State()
    tech = State()
    role = State()


def _rate_ok(user_id: int) -> bool:
    limit = get_ctx().settings.rate_limit_per_min
    now = time.monotonic()
    q = _rate[user_id]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= limit:
        return False
    q.append(now)
    return True


def _panel_link(user_id: int) -> str:
    return f"{get_ctx().settings.base_url}/chats/{user_id}"


def _who(user: dict) -> str:
    parts = [user.get("full_name") or "Noma'lum"]
    extra = ", ".join(x for x in (user.get("role"), user.get("tech_name")) if x)
    return f"{parts[0]} ({extra})" if extra else parts[0]


def _is_admin(tg_id: int) -> bool:
    return tg_id in get_ctx().settings.admin_ids


# ------------------------------------------------------------------ ro'yxatdan o'tish
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    c = get_ctx()
    await state.clear()
    tg = message.from_user
    user = await c.db.get_user_by_tg(tg.id)
    if user is None and _is_admin(tg.id):
        full = " ".join(x for x in (tg.first_name, tg.last_name) if x) or "Administrator"
        await c.db.create_user(tg.id, tg.username, full, None, None, "Administrator", status="approved")
        await message.answer(
            "👋 Assalomu alaykum, admin. Siz avtomatik ruxsat oldingiz.\n\nVeb-panel: "
            f"{c.settings.base_url}\nKirish uchun Telegram ID ingizni ({tg.id}) kiriting, kod shu yerga keladi.\n\n"
            + services.MAIN_MENU_HINT, reply_markup=main_menu())
        return
    if user is None or user["status"] == "rejected":
        await state.set_state(Reg.name)
        await message.answer(
            "👋 Assalomu alaykum! Bu Prof ta'lim tizimi bo'yicha yordamchi bot.\n"
            "Foydalanish uchun admin ruxsati kerak. Avval qisqa ma'lumot to'ldiring.\n\n"
            "👤 Ism va familiyangizni (otasining ismi bilan) yozing:")
        return
    if user["status"] == "approved":
        await message.answer("👋 Assalomu alaykum! " + services.MAIN_MENU_HINT,
                             reply_markup=main_menu(await services.effective_mode(user) == "admin"))
    elif user["status"] == "pending":
        await message.answer("⏳ So'rovingiz ko'rib chiqilmoqda. Ruxsat berilganda sizga xabar keladi.")


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❎ Bekor qilindi. Qayta boshlash uchun /start bosing.")


@router.message(Reg.name, F.text)
async def reg_name(message: Message, state: FSMContext):
    name = " ".join(message.text.split())
    if len(name) < 5 or len(name) > 120 or name.startswith("/"):
        await message.answer("Iltimos, ism va familiyangizni to'liq yozing:")
        return
    await state.update_data(full_name=name)
    await state.set_state(Reg.phone)
    await message.answer("📱 Telefon raqamingizni yuboring (pastdagi tugma orqali yoki +998901234567 ko'rinishida yozing):",
                         reply_markup=phone_keyboard())


@router.message(Reg.phone)
async def reg_phone(message: Message, state: FSMContext):
    phone = None
    if message.contact:
        phone = message.contact.phone_number
    elif message.text:
        phone = message.text
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) < 9 or len(digits) > 15:
        await message.answer("Telefon raqam noto'g'ri. Qayta yuboring:", reply_markup=phone_keyboard())
        return
    await state.update_data(phone="+" + digits)
    await state.set_state(Reg.tech)
    from aiogram.types import ReplyKeyboardRemove

    await message.answer("🏫 Qaysi texnikumda ishlaysiz? Texnikum nomini yozing:", reply_markup=ReplyKeyboardRemove())


@router.message(Reg.tech, F.text)
async def reg_tech(message: Message, state: FSMContext):
    tech = " ".join(message.text.split())
    if len(tech) < 3 or len(tech) > 150 or tech.startswith("/"):
        await message.answer("Texnikum nomini to'liq yozing:")
        return
    await state.update_data(tech_name=tech)
    await state.set_state(Reg.role)
    await message.answer("💼 Lavozimingiz / platformadagi rolingizni tanlang:", reply_markup=roles_keyboard())


@router.callback_query(Reg.role, F.data.startswith("role:"))
async def reg_role(cb: CallbackQuery, state: FSMContext):
    c = get_ctx()
    idx = int(cb.data.split(":")[1])
    if not 0 <= idx < len(ROLES):
        await cb.answer()
        return
    data = await state.get_data()
    await state.clear()
    tg = cb.from_user
    user = await c.db.get_user_by_tg(tg.id)
    if user is None:
        uid = await c.db.create_user(tg.id, tg.username, data["full_name"], data["phone"], data["tech_name"], ROLES[idx])
    else:
        uid = user["id"]
        await c.db.update_registration(uid, tg.username, data["full_name"], data["phone"], data["tech_name"], ROLES[idx])
    await cb.message.edit_text(f"💼 Rol: {ROLES[idx]}")
    await cb.message.answer("✅ So'rovingiz adminga yuborildi. Ruxsat berilgach sizga xabar keladi. Iltimos, kuting.")
    await cb.answer()
    new = await c.db.get_user(uid)
    await services.push({"type": "user", "user_id": uid})
    await services.notify_admins(
        "🆕 Yangi foydalanish so'rovi\n\n"
        f"👤 F.I.SH.: {new['full_name']}\n📱 Telefon: {new['phone']}\n🏫 Texnikum: {new['tech_name']}\n💼 Rol: {new['role']}\n"
        f"✈️ Telegram: {'@' + new['tg_username'] if new['tg_username'] else '-'} (ID {new['tg_id']})",
        reply_markup=approval_keyboard(uid))


@router.callback_query(F.data.startswith(("appr:", "rej:")))
async def cb_decide(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await cb.answer("Sizda ruxsat yo'q", show_alert=True)
        return
    action, uid = cb.data.split(":")
    status = "approved" if action == "appr" else "rejected"
    user = await services.decide_user(int(uid), status)
    if not user:
        await cb.answer("Foydalanuvchi topilmadi", show_alert=True)
        return
    label = "✅ Ruxsat berildi" if status == "approved" else "❌ Rad etildi"
    try:
        await cb.message.edit_text(f"{cb.message.text}\n\n{label}")
    except Exception:  # noqa: BLE001
        pass
    await cb.answer(label)


# ------------------------------------------------------------------ yordamchi buyruqlar
async def _approved_user(message: Message) -> dict | None:
    c = get_ctx()
    user = await c.db.get_user_by_tg(message.from_user.id)
    if user is None:
        await message.answer("Botdan foydalanish uchun /start bosing.")
        return None
    if user["status"] == "approved":
        return user
    if user["status"] == "pending":
        await message.answer("⏳ So'rovingiz hali ko'rib chiqilmoqda. Ruxsat berilganda sizga xabar keladi.")
    elif user["status"] == "rejected":
        await message.answer("❌ So'rovingiz rad etilgan. Qayta so'rov yuborish uchun /start bosing.")
    return None  # bloklangan foydalanuvchiga javob berilmaydi


@router.message(Command("help"))
@router.message(is_button(LBL_HELP))
async def cmd_help(message: Message):
    if await _approved_user(message):
        await message.answer(HELP_TEXT)


@router.message(Command("panel"))
async def cmd_panel(message: Message):
    if _is_admin(message.from_user.id):
        await message.answer(f"Veb-panel: {get_ctx().settings.base_url}\nKirish uchun Telegram ID ingiz: {message.from_user.id}")


@router.message(Command("admin"))
@router.message(is_button(LBL_ADMIN))
async def cmd_admin(message: Message):
    c = get_ctx()
    user = await _approved_user(message)
    if not user:
        return
    await c.db.set_mode(user["id"], "admin")
    await c.db.set_attention(user["id"], True)
    await c.db.add_message(user["id"], "user", "text", text="[Adminga murojaat so'raldi]", found=None)
    await services.push({"type": "message", "user_id": user["id"]})
    await message.answer(
        "Adminga xabar yuborildi. Savolingizni yozib qoldiring.\n"
        f"{services.availability_note()}\n\n"
        "Botga qaytish uchun \"Botga qaytish\" tugmasini bosing.", reply_markup=main_menu(admin_mode=True))
    await services.notify_admins(f"🙋 Adminga murojaat: {_who(user)}\n🔗 Panel: {_panel_link(user['id'])}")


@router.message(Command("bot"))
@router.message(is_button(LBL_BOT))
async def cmd_bot(message: Message):
    c = get_ctx()
    user = await _approved_user(message)
    if not user:
        return
    await c.db.set_mode(user["id"], "bot")
    await services.push({"type": "user", "user_id": user["id"]})
    await message.answer("🤖 Bot rejimiga qaytdingiz. Savolingizni yozing.", reply_markup=main_menu())


# ------------------------------------------------------------------ FAQ
def _faq_topics_kb(topics: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for t in topics:
        name = t["topic"] if t["topic"] in TOPICS else "Boshqa"
        rows.append([InlineKeyboardButton(text=f"📂 {name} ({t['n']})", callback_data=f"faqt:{TOPICS.index(name)}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(is_button(LBL_FAQ))
async def cmd_faq(message: Message):
    c = get_ctx()
    if not await _approved_user(message):
        return
    topics = await c.db.faq_topics()
    if not topics:
        await message.answer("Hozircha tayyor ro'yxat yo'q. Savolingizni yozing, javob beraman.")
        return
    await message.answer("❓ Ko'p so'raladigan savollar. Mavzuni tanlang:", reply_markup=_faq_topics_kb(topics))


@router.callback_query(F.data == "faqb")
async def cb_faq_back(cb: CallbackQuery):
    topics = await get_ctx().db.faq_topics()
    try:
        await cb.message.edit_text("❓ Ko'p so'raladigan savollar. Mavzuni tanlang:", reply_markup=_faq_topics_kb(topics))
    except Exception:  # noqa: BLE001
        pass
    await cb.answer()


@router.callback_query(F.data.startswith("faqt:"))
async def cb_faq_topic(cb: CallbackQuery):
    c = get_ctx()
    user = await c.db.get_user_by_tg(cb.from_user.id)
    if not user or user["status"] != "approved":
        await cb.answer()
        return
    idx = int(cb.data.split(":")[1])
    if not 0 <= idx < len(TOPICS):
        await cb.answer()
        return
    items = await c.db.faq_by_topic(TOPICS[idx])
    rows = [[InlineKeyboardButton(text=f"❓ {i['question'][:58]}", callback_data=f"faqq:{i['id']}")] for i in items[:20]]
    rows.append([InlineKeyboardButton(text="⬅️ Mavzular", callback_data="faqb")])
    try:
        await cb.message.edit_text(f"📂 {TOPICS[idx]}. Savolni tanlang:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    except Exception:  # noqa: BLE001
        pass
    await cb.answer()


@router.callback_query(F.data.startswith("faqq:"))
async def cb_faq_item(cb: CallbackQuery):
    c = get_ctx()
    user = await c.db.get_user_by_tg(cb.from_user.id)
    if not user or user["status"] != "approved":
        await cb.answer()
        return
    item = await c.db.get_faq(int(cb.data.split(":")[1]))
    if not item or item["status"] != "approved":
        await cb.answer("Topilmadi", show_alert=True)
        return
    await c.db.inc_faq_views(item["id"])
    await cb.message.answer(bot_html(item["question"], item["answer"], "Ko'p so'raladigan savollar"), parse_mode="HTML")
    await cb.answer()


# ------------------------------------------------------------------ video darslar
def _video_card(v: dict) -> str:
    import html as _h

    desc = f"\n{_h.escape(v['description'], quote=False)}" if v.get("description") else ""
    return (f"🎬 <b>{_h.escape(v['title'], quote=False)}</b>{desc}\n\n"
            f'▶️ <a href="{_h.escape(v["url"], quote=True)}">Videoni ko\'rish</a>')


def _video_list_kb(videos: list[dict], back: bool = False) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"▶️ {v['title'][:58]}", callback_data=f"vid:{v['id']}")] for v in videos[:25]]
    if back:
        rows.append([InlineKeyboardButton(text="⬅️ Mavzular", callback_data="vidb")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _video_topics_kb(videos: list[dict]) -> InlineKeyboardMarkup:
    counts: dict[str, int] = {}
    for v in videos:
        name = v["topic"] if v.get("topic") in TOPICS else "Boshqa"
        counts[name] = counts.get(name, 0) + 1
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📁 {n} ({k})", callback_data=f"vidt:{TOPICS.index(n)}")] for n, k in counts.items()])


@router.message(is_button(LBL_VIDEO))
async def cmd_videos(message: Message):
    c = get_ctx()
    if not await _approved_user(message):
        return
    videos = await c.db.list_lib_videos(active_only=True)
    if not videos:
        await message.answer("🎬 Hozircha video darslar qo'shilmagan.")
    elif len(videos) <= 12:
        await message.answer("🎬 Video darslar:", reply_markup=_video_list_kb(videos))
    else:
        await message.answer("🎬 Video darslar. Mavzuni tanlang:", reply_markup=_video_topics_kb(videos))


@router.callback_query(F.data == "vidb")
async def cb_video_back(cb: CallbackQuery):
    videos = await get_ctx().db.list_lib_videos(active_only=True)
    try:
        await cb.message.edit_text("🎬 Video darslar. Mavzuni tanlang:", reply_markup=_video_topics_kb(videos))
    except Exception:  # noqa: BLE001
        pass
    await cb.answer()


@router.callback_query(F.data.startswith("vidt:"))
async def cb_video_topic(cb: CallbackQuery):
    c = get_ctx()
    user = await c.db.get_user_by_tg(cb.from_user.id)
    if not user or user["status"] != "approved":
        await cb.answer()
        return
    idx = int(cb.data.split(":")[1])
    if not 0 <= idx < len(TOPICS):
        await cb.answer()
        return
    name = TOPICS[idx]
    items = [v for v in await c.db.list_lib_videos(active_only=True)
             if (v["topic"] if v.get("topic") in TOPICS else "Boshqa") == name]
    try:
        await cb.message.edit_text(f"📁 {name}. Videoni tanlang:", reply_markup=_video_list_kb(items, back=True))
    except Exception:  # noqa: BLE001
        pass
    await cb.answer()


@router.callback_query(F.data.startswith("vid:"))
async def cb_video_item(cb: CallbackQuery):
    c = get_ctx()
    user = await c.db.get_user_by_tg(cb.from_user.id)
    if not user or user["status"] != "approved":
        await cb.answer()
        return
    v = await c.db.get_lib_video(int(cb.data.split(":")[1]))
    if not v or not v["active"]:
        await cb.answer("Topilmadi", show_alert=True)
        return
    await c.db.inc_video_views(v["id"])
    await cb.message.answer(_video_card(v), parse_mode="HTML")
    await cb.answer()


# ------------------------------------------------------------------ kunlik test
@router.message(Command("test"))
@router.message(is_button(LBL_QUIZ))
async def cmd_quiz(message: Message):
    user = await _approved_user(message)
    if not user:
        return
    note = await quiz.open_today(user)
    if note:
        await message.answer(note)


@router.callback_query(F.data.startswith("qz:"))
async def cb_quiz(cb: CallbackQuery):
    c = get_ctx()
    user = await c.db.get_user_by_tg(cb.from_user.id)
    if not user or user["status"] != "approved":
        await cb.answer()
        return
    try:
        _, sid, qid, chosen = cb.data.split(":")
        res = await quiz.handle_answer(user, int(sid), int(qid), int(chosen))
    except ValueError:
        res = None
    if res is None:
        await cb.answer("Bu savolga allaqachon javob berilgan", show_alert=False)
        return
    edited, nxt_text, nxt_kb = res
    try:
        await cb.message.edit_text(edited, parse_mode="HTML", reply_markup=None)
    except Exception:  # noqa: BLE001
        pass
    await cb.message.answer(nxt_text, parse_mode="HTML", reply_markup=nxt_kb)
    await cb.answer()


@router.callback_query(F.data.startswith("ann:"))
async def cb_announcement(cb: CallbackQuery):
    """E'londagi "Tushundim" tugmasi."""
    c = get_ctx()
    user = await c.db.get_user_by_tg(cb.from_user.id)
    if not user or user["status"] != "approved":
        await cb.answer()
        return
    try:
        ann_id = int(cb.data.split(":")[1])
    except (ValueError, IndexError):
        await cb.answer()
        return
    fresh = await announce.acknowledge(ann_id, user["id"])
    if fresh:
        await services.push({"type": "announcement", "id": ann_id})
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:  # noqa: BLE001
        pass
    await cb.answer("Rahmat, qabul qilindi ✅" if fresh else "Avval tasdiqlangan")


# ------------------------------------------------------------------ rasm
@router.message(StateFilter(None), F.photo)
async def on_photo(message: Message):
    """Rasm: faqat file_id saqlanadi (fayl hech qayerga yuklanmaydi), OpenAI ga yuborilmaydi, bot javob bermaydi."""
    c = get_ctx()
    user = await c.db.get_user_by_tg(message.from_user.id)
    if not user or user["status"] != "approved":
        return
    caption = message.caption
    await c.db.add_message(user["id"], "user", "photo", text=caption, file_id=message.photo[-1].file_id,
                           tg_message_id=message.message_id)
    await c.db.set_attention(user["id"], True)
    await services.push({"type": "message", "user_id": user["id"]})
    last = parse_ts(user.get("photo_notified_at"))
    if last and (utcnow() - last).total_seconds() < 60:
        return
    await c.db.touch_photo_notified(user["id"])
    await services.notify_admins(f"🖼 Rasm keldi: {_who(user)}\n🔗 Panel: {_panel_link(user['id'])}")


# ------------------------------------------------------------------ matn (asosiy)
@router.message(StateFilter(None), F.text, ~F.text.startswith("/"))
async def on_text(message: Message):
    c = get_ctx()
    user = await _approved_user(message)
    if not user:
        return
    text = message.text.strip()
    if not text:
        return
    history = [
        {"sender": h["sender"], "text": mask_sensitive(h["text"])[0]}
        for h in await c.db.ai_history(user["id"], c.settings.history_turns)
    ]
    msg_id = await c.db.add_message(user["id"], "user", "text", text=text, tg_message_id=message.message_id)
    await services.push({"type": "message", "user_id": user["id"]})

    if await services.effective_mode(user) == "admin":
        await c.db.set_attention(user["id"], True)
        return
    if not _rate_ok(user["id"]):
        await message.answer(system_html("Juda ko'p savol yuborildi. Iltimos, 1 daqiqadan keyin qayta urinib ko'ring."),
                             parse_mode="HTML")
        return

    masked, _n = mask_sensitive(text)
    kb_hits = kb_mod.find_relevant(await c.db.list_kb(active_only=True), masked)
    lib = await c.db.list_lib_videos(active_only=True)
    try:
        async with ChatActionSender.typing(bot=c.bot, chat_id=message.chat.id):
            result = await c.agent.answer(masked, user.get("role"), history, kb=kb_hits, videos=lib)
    except AgentError:
        log.exception("Agent xatosi")
        await c.db.update_message_analysis(msg_id, None, False)
        await _escalate(user, message, msg_id, text,
                        "Hozir javob bera olmayapman. Savolingiz adminga yuborildi.")
        return

    await c.db.update_message_analysis(msg_id, result.topic, result.found)
    if not result.found:
        await _escalate(user, message, msg_id, masked,
                        "Bu savol bo'yicha qo'llanmada aniq javob topa olmadim. Savolingiz adminga yuborildi.")
        return

    video = next(((v["title"], v["url"]) for v in lib if v["id"] == result.video_id), None)
    if video:
        await c.db.inc_video_views(result.video_id)
    await c.db.add_message(
        user["id"], "bot", "text", text=bot_plain(result.title, result.answer[:3500], result.section, video),
        topic=result.topic, found=True, sources=result.sources,
        tokens_in=result.tokens_in, tokens_out=result.tokens_out)
    await message.answer(bot_html(result.title, result.answer[:3500], result.section, video), parse_mode="HTML",
                         disable_web_page_preview=True)
    await services.push({"type": "message", "user_id": user["id"]})


async def _escalate(user: dict, message: Message, user_msg_id: int, question_text: str, user_reply: str):
    c = get_ctx()
    await c.db.set_attention(user["id"], True)
    user_reply = f"{user_reply}\n{services.availability_note()}"
    await c.db.add_message(user["id"], "bot", "text", text=user_reply, found=False)
    await message.answer(system_html(user_reply), parse_mode="HTML")
    await services.push({"type": "message", "user_id": user["id"]})
    await services.notify_admins(
        f"❓ Javobsiz savol: {_who(user)}\n\n\"{question_text[:600]}\"\n\nPanel: {_panel_link(user['id'])}")


# ------------------------------------------------------------------ boshqa turdagi kontent
@router.message(StateFilter(None), ~F.text & ~F.photo)
async def on_other(message: Message):
    c = get_ctx()
    user = await c.db.get_user_by_tg(message.from_user.id)
    if not user or user["status"] != "approved":
        return
    kind = message.content_type.value if hasattr(message.content_type, "value") else str(message.content_type)
    await c.db.add_message(user["id"], "user", "other", text=f"[{kind}] qabul qilinmadi")
    await services.push({"type": "message", "user_id": user["id"]})
    await message.answer("🚫 Faqat matn va rasm qabul qilinadi. Audio, video va fayllarni yubora olmaysiz.")
