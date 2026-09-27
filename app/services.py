"""Bot va veb-panel uchun umumiy amallar."""
from __future__ import annotations

import html
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram.exceptions import TelegramAPIError
from aiogram.types import BufferedInputFile

from .context import get_ctx
from .db import parse_ts, utcnow
from .format import admin_html

log = logging.getLogger(__name__)

MAIN_MENU_HINT = "✍️ Savolingizni yozing. Rasm yuborsangiz, u faqat adminga ko'rinadi (bot rasmni ko'rmaydi)."


async def push(event: dict) -> None:
    await get_ctx().hub.broadcast(event)


async def notify_admins(text: str, reply_markup=None) -> None:
    c = get_ctx()
    for admin_id in c.settings.admin_ids:
        try:
            await c.bot.send_message(admin_id, text, reply_markup=reply_markup)
        except TelegramAPIError as exc:
            log.warning("Adminga (%s) xabar yuborib bo'lmadi: %s", admin_id, exc)
        except Exception:  # noqa: BLE001
            log.exception("Adminga xabar yuborishda kutilmagan xato")


async def notify_for_user(user: dict, text: str) -> None:
    """Suhbat adminga biriktirilgan bo'lsa faqat unga, aks holda hamma adminlarga xabar yuboradi."""
    c = get_ctx()
    fresh = await c.db.get_user(user["id"]) or user
    owner = fresh.get("assigned_to")
    if owner and owner in c.settings.admin_ids:
        try:
            await c.bot.send_message(owner, text)
        except TelegramAPIError as exc:
            log.warning("Adminga (%s) xabar yuborib bo'lmadi: %s", owner, exc)
        return
    await notify_admins(text)


async def effective_mode(user: dict) -> str:
    """Admin rejimi belgilangan vaqtdan keyin avtomatik 'bot' ga qaytadi."""
    if user["mode"] != "admin":
        return "bot"
    c = get_ctx()
    since = parse_ts(user.get("mode_since"))
    if since and utcnow() - since > timedelta(minutes=c.settings.admin_mode_timeout_min):
        await c.db.set_mode(user["id"], "bot")
        user["mode"] = "bot"
        return "bot"
    return "admin"


async def decide_user(user_id: int, status: str) -> dict | None:
    """Foydalanuvchiga ruxsat berish / rad etish / bloklash. Foydalanuvchiga Telegram orqali xabar yuboriladi."""
    from .bot.keyboards import main_menu

    c = get_ctx()
    user = await c.db.get_user(user_id)
    if not user:
        return None
    old = user["status"]
    await c.db.set_status(user_id, status)
    user["status"] = status
    if old != status:
        try:
            if status == "approved":
                await c.bot.send_message(
                    user["tg_id"],
                    "✅ Sizga botdan foydalanish uchun ruxsat berildi.\n\n" + MAIN_MENU_HINT,
                    reply_markup=main_menu(),
                )
            elif status == "rejected":
                await c.bot.send_message(
                    user["tg_id"], "❌ So'rovingiz rad etildi. Savollar bo'lsa, admin bilan bog'laning. "
                                   "Qayta so'rov yuborish uchun /start bosing.")
        except TelegramAPIError as exc:
            log.warning("Foydalanuvchiga (%s) xabar yuborib bo'lmadi: %s", user["tg_id"], exc)
    await push({"type": "user", "user_id": user_id})
    return user


async def admin_send(user_id: int, text: str | None = None, admin_id: int | None = None, file_bytes: bytes | None = None,
                     filename: str = "file", content_type: str = "") -> int:
    """Admin veb-paneldan foydalanuvchiga matn / rasm / video yuboradi. Fayl diskka yozilmaydi (faqat xotirada)."""
    c = get_ctx()
    user = await c.db.get_user(user_id)
    if not user:
        raise ValueError("Foydalanuvchi topilmadi")
    text = (text or "").strip() or None
    author = c.settings.admin_name(admin_id)
    kind, file_id, tg_msg_id = "text", None, None
    if file_bytes:
        inp = BufferedInputFile(file_bytes, filename=filename)
        caption = admin_html(author, text[:800]) if text else f"🧑‍💼 <b>{html.escape(author, quote=False)}</b>"
        if content_type.startswith("image/"):
            sent = await c.bot.send_photo(user["tg_id"], inp, caption=caption, parse_mode="HTML")
            kind, file_id = "photo", sent.photo[-1].file_id
        elif content_type.startswith("video/"):
            sent = await c.bot.send_video(user["tg_id"], inp, caption=caption, parse_mode="HTML", supports_streaming=True)
            kind, file_id = "video", sent.video.file_id
        else:
            raise ValueError("Faqat rasm (skrinshot) va video yuborish mumkin")
        tg_msg_id = sent.message_id
        if text and len(text) > 800:
            await c.bot.send_message(user["tg_id"], admin_html(author, text[800:]), parse_mode="HTML")
    elif text:
        sent = await c.bot.send_message(user["tg_id"], admin_html(author, text), parse_mode="HTML")
        tg_msg_id = sent.message_id
    else:
        raise ValueError("Xabar bo'sh")
    msg_id = await c.db.add_message(user_id, "admin", kind, text=text, file_id=file_id, tg_message_id=tg_msg_id,
                                   author=author)
    # admin javob yozganda suhbat admin rejimiga o'tadi va "diqqat" belgisi olinadi
    await c.db.set_mode(user_id, "admin")
    await c.db.set_attention(user_id, False)
    await c.db.mark_read(user_id)
    if admin_id and not user.get("assigned_to"):
        await c.db.assign_chat(user_id, admin_id)   # birinchi javob bergan admin suhbatni o'ziga biriktiradi
    await push({"type": "message", "user_id": user_id})
    return msg_id


# ------------------------------------------------------------------ ish vaqti va eslatmalar
def local_now() -> datetime:
    return datetime.now(ZoneInfo(get_ctx().settings.timezone))


def _hm(t: tuple[int, int]) -> str:
    return f"{t[0]:02d}:{t[1]:02d}"


# ------------------------------------------------------------------ ish vaqti, dam olish kunlari va bayramlar
WEEKDAYS_UZ = ["dushanba", "seshanba", "chorshanba", "payshanba", "juma", "shanba", "yakshanba"]
_hol_exact: dict[str, str] = {}
_hol_yearly: dict[str, str] = {}


def _parse_hm(value: str | None, default: tuple[int, int]) -> tuple[int, int]:
    try:
        h, m = (value or "").strip().split(":")
        return int(h), int(m)
    except Exception:  # noqa: BLE001
        return default


async def load_worktime() -> None:
    """Panelda saqlangan ish vaqti va bayramlarni xotiraga yuklaydi (ishga tushganda va saqlanganda chaqiriladi)."""
    c = get_ctx()
    s = c.settings
    s.work_start = _parse_hm(await c.db.get_kv("work_start"), s.work_start)
    s.work_end = _parse_hm(await c.db.get_kv("work_end"), s.work_end)
    days = (await c.db.get_kv("work_days") or "").strip()
    if days:
        parsed = frozenset(int(x) for x in days.split(",") if x.strip().isdigit() and 1 <= int(x) <= 7)
        if parsed:
            s.work_days = parsed
    _hol_exact.clear()
    _hol_yearly.clear()
    for h in await c.db.list_holidays():
        (_hol_yearly if h["recurring"] else _hol_exact)[h["day"]] = h["name"]


def holiday_name(day) -> str | None:
    return _hol_exact.get(day.strftime("%Y-%m-%d")) or _hol_yearly.get(day.strftime("%m-%d"))


def is_workday(day) -> bool:
    return day.isoweekday() in get_ctx().settings.work_days and not holiday_name(day)


def in_work_hours(now: datetime | None = None) -> bool:
    s = get_ctx().settings
    now = now or local_now()
    if not is_workday(now):
        return False
    return s.work_start <= (now.hour, now.minute) < s.work_end


def next_work_start(now: datetime | None = None) -> datetime:
    s = get_ctx().settings
    now = now or local_now()
    for i in range(0, 21):
        d = now + timedelta(days=i)
        if is_workday(d):
            start = d.replace(hour=s.work_start[0], minute=s.work_start[1], second=0, microsecond=0)
            if start > now:
                return start
    return now


def availability_note(now: datetime | None = None) -> str:
    """Foydalanuvchiga admin qachon javob berishi haqida yumshoq ogohlantirish."""
    s = get_ctx().settings
    now = now or local_now()
    rng = f"{_hm(s.work_start)}–{_hm(s.work_end)}"
    if in_work_hours(now):
        return f"🕘 Admin ish vaqtida (ish kunlari {rng}) tez orada javob beradi."
    hol = holiday_name(now)
    nxt = next_work_start(now)
    if nxt.date() == now.date():
        when = f"bugun soat {_hm(s.work_start)} dan"
    elif nxt.date() == (now + timedelta(days=1)).date():
        when = f"ertaga soat {_hm(s.work_start)} dan"
    else:
        when = f"{WEEKDAYS_UZ[nxt.weekday()]} kuni ({nxt.strftime('%d.%m')}) soat {_hm(s.work_start)} dan"
    if hol:
        head = f"🎉 Bugun dam olish kuni ({hol}), shuning uchun admin javob bera olmasligi mumkin."
    elif now.isoweekday() not in s.work_days:
        head = "🌿 Bugun dam olish kuni, shuning uchun admin javob bera olmasligi mumkin."
    else:
        head = (f"🌙 Hozir ish vaqtidan tashqari (ish kunlari {rng}), shuning uchun admin darhol javob bera olmasligi mumkin.")
    return f"{head} Savolingiz qabul qilindi, admin {when} javob beradi. Sabringiz uchun rahmat."


def in_remind_window(now: datetime | None = None) -> bool:
    s = get_ctx().settings
    now = now or local_now()
    return s.remind_from <= (now.hour, now.minute) <= s.remind_to


async def remind_admins(now: datetime | None = None) -> int:
    """Javob kutayotgan (kamida REMIND_EVERY_MIN daqiqa) suhbatlar haqida adminlarga xabar. Biriktirilgan suhbatlar
    faqat o'z adminiga, biriktirilmaganlari hammaga boradi. Kutayotgan suhbatlar sonini qaytaradi."""
    c = get_ctx()
    now = now or local_now()
    if not in_remind_window(now):
        return 0
    rows = await c.db.waiting_chats()
    utc_now = utcnow()
    items: list[tuple[int | None, str]] = []
    for r in rows:
        since = parse_ts(r.get("last_message_at"))
        waited = int((utc_now - since).total_seconds() // 60) if since else 0
        if waited < max(1, c.settings.remind_every_min - 1):
            continue
        what = "[rasm]" if r.get("last_kind") == "photo" else (r.get("last_text") or "")[:60]
        owner = r.get("assigned_to")
        items.append((owner if owner in c.settings.admin_ids else None,
                      f"{r.get('full_name') or 'Noma`lum'} ({waited} daq.): {what}"))
    if not items:
        return 0
    for admin_id in c.settings.admin_ids:
        mine = [t for o, t in items if o is None or o == admin_id]
        if not mine:
            continue
        lines = [f"{i + 1}. {t}" for i, t in enumerate(mine[:10])]
        more = f"\n... va yana {len(mine) - 10} ta" if len(mine) > 10 else ""
        try:
            await c.bot.send_message(admin_id, f"⏰ Javob kutayotgan suhbatlar: {len(mine)} ta\n\n" + "\n".join(lines)
                                     + more + f"\n\n🔗 Panel: {c.settings.base_url}/chats?filter=attention")
        except TelegramAPIError as exc:
            log.warning("Adminga (%s) eslatma yuborib bo'lmadi: %s", admin_id, exc)
    return len(items)
