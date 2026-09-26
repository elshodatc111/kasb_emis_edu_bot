"""Kunlik viktorina: har bir xodimga roli bo'yicha 5 ta takrorlanmas savol, 3 variantli."""
from __future__ import annotations

import asyncio
import html
import logging
import math
from datetime import datetime, timedelta

from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .agent import AgentError
from .constants import ROLES
from .context import get_ctx

log = logging.getLogger(__name__)

TICK_MIN = 2
LETTERS = "ABC"
_locks: dict[str, asyncio.Lock] = {}
_failed: set[tuple[str, str]] = set()  # (kun, rol): savol tuzib bo'lmagan


def today(now: datetime | None = None) -> str:
    from .services import local_now

    return (now or local_now()).strftime("%Y-%m-%d")


def question_html(idx: int, total: int, q: dict, result: str | None = None) -> str:
    lines = [f"🧩 <b>Kunlik test</b> · {idx + 1}/{total}", "", f"<b>{html.escape(q['question'], quote=False)}</b>", ""]
    for i, o in enumerate(q["options"]):
        lines.append(f"{LETTERS[i]}) {html.escape(o, quote=False)}")
    if result:
        lines += ["", result]
    return "\n".join(lines)


def result_text(q: dict, chosen: int) -> str:
    if chosen == q["correct"]:
        out = "✅ <b>Siz to'g'ri javob berdingiz.</b>"
    else:
        right = f"{LETTERS[q['correct']]}) {q['options'][q['correct']]}"
        out = f"❌ <b>Siz noto'g'ri javob berdingiz.</b>\nTo'g'ri javob: <b>{html.escape(right, quote=False)}</b>"
    if q.get("explanation"):
        out += f"\n💡 {html.escape(q['explanation'], quote=False)}"
    return out


def keyboard(session_id: int, q: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"🔹 {LETTERS[i]}", callback_data=f"qz:{session_id}:{q['id']}:{i}") for i in range(3)]])


def summary_text(score: int, total: int) -> str:
    if score == total:
        note = "Ajoyib natija!"
    elif score * 2 >= total:
        note = "Yaxshi natija."
    else:
        note = "Qo'llanmani yana bir bor ko'rib chiqing, savollaringiz bo'lsa botga yozing."
    return f"🏁 <b>Test yakunlandi.</b> Natija: <b>{score}/{total}</b>\n{note}\nErtaga yangi savollar keladi."


async def ensure_pool(role: str, user_id: int, need: int) -> int:
    """Foydalanuvchi uchun kamida `need` ta ko'rilmagan savol bo'lishini ta'minlaydi (kerak bo'lsa AI yangi savol tuzadi)."""
    c = get_ctx()
    lock = _locks.setdefault(role, asyncio.Lock())
    async with lock:
        for _attempt in range(2):
            have = await c.db.quiz_unseen_count(role, user_id)
            if have >= need:
                return have
            try:
                items = await c.agent.quiz_questions(role, 15, await c.db.quiz_existing_questions(role))
            except AgentError:
                log.exception("Viktorina savollari tuzilmadi (%s)", role)
                break
            if not await c.db.add_quiz_questions(role, items):
                break
        return await c.db.quiz_unseen_count(role, user_id)


async def _send_question(user: dict, session: dict) -> None:
    c = get_ctx()
    qids = session["question_ids"]
    q = await c.db.get_quiz_question(qids[session["current"]])
    await c.bot.send_message(user["tg_id"], question_html(session["current"], len(qids), q), parse_mode="HTML",
                             reply_markup=keyboard(session["id"], q))


async def start_session(user: dict, day: str | None = None) -> dict | None:
    """Foydalanuvchi uchun bugungi sessiyani yaratadi va birinchi savolni yuboradi. Savol topilmasa None."""
    c = get_ctx()
    day = day or today()
    role = user.get("role")
    if role not in ROLES:
        return None
    size = c.settings.quiz_size
    await ensure_pool(role, user["id"], size)
    qids = await c.db.quiz_pick_unseen(role, user["id"], size)
    if not qids:
        return None
    sid = await c.db.create_quiz_session(user["id"], day, qids)
    session = await c.db.get_quiz_session_by_id(sid)
    try:
        await _send_question(user, session)
    except TelegramAPIError as exc:
        log.warning("Viktorina yuborilmadi (%s): %s", user["tg_id"], exc)
    return session


async def open_today(user: dict) -> str:
    """'Kunlik test' tugmasi: xabar matnini qaytaradi (yoki savolni qayta yuboradi)."""
    c = get_ctx()
    day = today()
    session = await c.db.get_quiz_session(user["id"], day)
    if session is None:
        if user.get("role") not in ROLES:
            return "Test faqat ro'yxatdagi rollar uchun. Rolingizni admin panelda to'g'rilashi mumkin."
        session = await start_session(user, day)
        return "" if session else "Hozircha test savollarini tayyorlab bo'lmadi. Keyinroq urinib ko'ring."
    if session["status"] == "done":
        return f"Bugungi test yakunlangan: {session['score']}/{len(session['question_ids'])}. Ertaga yangi savollar keladi."
    await _send_question(user, session)
    return ""


async def handle_answer(user: dict, session_id: int, qid: int, chosen: int):
    """Javobni qayta ishlaydi. (yangi matn HTML, keyingi_xabar yoki None) qaytaradi; xato bo'lsa None."""
    c = get_ctx()
    session = await c.db.get_quiz_session_by_id(session_id)
    if not session or session["user_id"] != user["id"] or session["status"] == "done":
        return None
    qids = session["question_ids"]
    if session["current"] >= len(qids) or qids[session["current"]] != qid or not 0 <= chosen <= 2:
        return None
    q = await c.db.get_quiz_question(qid)
    if not q:
        return None
    ok = await c.db.record_quiz_answer(session_id, user["id"], qid, chosen, chosen == q["correct"])
    if not ok:
        return None
    edited = question_html(session["current"], len(qids), q, result_text(q, chosen))
    session = await c.db.get_quiz_session_by_id(session_id)
    if session["current"] >= len(qids):
        await c.db.finish_quiz_session(session_id)
        return edited, summary_text(session["score"], len(qids)), None
    nxt = await c.db.get_quiz_question(qids[session["current"]])
    return edited, question_html(session["current"], len(qids), nxt), keyboard(session_id, nxt)


async def tick(now: datetime | None = None) -> int:
    """Har 2 daqiqada: viktorina oynasida (12:20-13:00) hali olmagan xodimlarga bir tekis yuboradi."""
    from .services import local_now

    c = get_ctx()
    s = c.settings
    now = now or local_now()
    if now.isoweekday() not in s.quiz_days:
        return 0
    start = now.replace(hour=s.quiz_start[0], minute=s.quiz_start[1], second=0, microsecond=0)
    end = now.replace(hour=s.quiz_end[0], minute=s.quiz_end[1], second=0, microsecond=0)
    if not (start <= now <= end):
        return 0
    day = today(now)
    cands = await c.db.quiz_candidates(day, ROLES)
    if not cands:
        return 0
    ticks_left = max(1, int((end - now).total_seconds() // 60 // TICK_MIN) + 1)
    batch = math.ceil(len(cands) / ticks_left)
    sent = 0
    todo = [u for u in cands if (day, u.get("role")) not in _failed][:batch]
    for u in todo:
        try:
            if await start_session(u, day):
                sent += 1
            else:
                _failed.add((day, u.get("role")))  # AI ni har 2 daqiqada qayta-qayta chaqirmaslik uchun
        except Exception:  # noqa: BLE001
            log.exception("Viktorina yuborishda xato (user %s)", u.get("id"))
    return sent


async def prepare_pools() -> int:
    """Viktorina oldidan (masalan 11:30 da) har bir rol uchun savollar zaxirasini tayyorlaydi."""
    c = get_ctx()
    made = 0
    for role in ROLES:
        users = [u for u in await c.db.quiz_candidates(today(), [role])]
        if not users:
            continue
        worst = min([await c.db.quiz_unseen_count(role, u["id"]) for u in users])
        if worst < c.settings.quiz_size * 2:
            before = await c.db.quiz_pool_size(role)
            await ensure_pool(role, users[0]["id"], c.settings.quiz_size * 2)
            made += (await c.db.quiz_pool_size(role)) - before
    return made


async def send_all_now() -> int:
    """Admin tugmasi: bugun hali test olmagan hamma xodimga darhol yuboradi."""
    c = get_ctx()
    day = today()
    sent = 0
    for u in await c.db.quiz_candidates(day, ROLES):
        try:
            if await start_session(u, day):
                sent += 1
        except Exception:  # noqa: BLE001
            log.exception("Viktorina yuborishda xato (user %s)", u.get("id"))
    return sent
