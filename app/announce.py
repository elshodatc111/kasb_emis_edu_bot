"""Ommaviy e'lonlar: oldindan ko'rish, hozir yoki rejalashtirilgan yuborish, yetkazish hisoboti."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from .context import get_ctx
from .format import ann_html, visible_len
from .privacy import mask_sensitive

log = logging.getLogger(__name__)

KINDS = ("info", "important", "reminder")
CAPTION_LIMIT = 1024
TEXT_LIMIT = 4096
SEND_DELAY = 0.06  # ~16 xabar/soniya (Telegram limiti ~30)
ACK_LABEL = "✅ Tushundim"

_tasks: dict[int, asyncio.Task] = {}


def keyboard(ann: dict) -> InlineKeyboardMarkup | None:
    if not ann.get("ack_required"):
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=ACK_LABEL, callback_data=f"ann:{ann['id']}")]])


def render(ann: dict) -> str:
    return ann_html(ann["kind"], ann.get("title"), ann.get("text"), ann.get("author") or "Administrator")


def check_length(kind: str, title: str, text: str, has_image: bool, author: str) -> str | None:
    """Xato matni yoki None. Rasm bilan izoh 1024 belgidan oshmasligi kerak."""
    n = visible_len(ann_html(kind, title, text, author))
    if has_image and n > CAPTION_LIMIT:
        return (f"Rasm bilan yuboriladigan xabar (sarlavha va ustki/ostki yozuvlar bilan) {CAPTION_LIMIT} belgidan oshmasligi kerak. "
                f"Hozir: {n}. Matnni {n - CAPTION_LIMIT} belgiga qisqartiring.")
    if n > TEXT_LIMIT:
        return f"Xabar juda uzun ({n} belgi, chegara {TEXT_LIMIT})."
    return None


async def _send_one(tg_id: int, ann: dict) -> int:
    c = get_ctx()
    body = render(ann)
    if ann.get("image_file_id"):
        m = await c.bot.send_photo(tg_id, ann["image_file_id"], caption=body, parse_mode="HTML",
                                   reply_markup=keyboard(ann))
    else:
        m = await c.bot.send_message(tg_id, body, parse_mode="HTML", reply_markup=keyboard(ann))
    return m.message_id


async def make_draft(kind: str, title: str, text: str, image: bytes | None, filename: str, audience: dict,
                     ack_required: bool, admin_id: int) -> int:
    """Qoralama yaratadi. Rasm faqat Telegramga (adminning o'ziga oldindan ko'rish sifatida) yuboriladi va file_id olinadi;
    diskka yozilmaydi."""
    c = get_ctx()
    author = c.settings.admin_name(admin_id)
    if kind not in KINDS:
        raise ValueError("E'lon turi noto'g'ri")
    title, text = " ".join((title or "").split()), (text or "").strip()
    if not text and not image:
        raise ValueError("Matn yoki rasm kiriting")
    err = check_length(kind, title, text, bool(image), author)
    if err:
        raise ValueError(err)
    if mask_sensitive(text)[1] or mask_sensitive(title)[1]:
        raise ValueError("Matnda PINFL yoki pasport raqami bor. E'londan shaxsiy ma'lumotlarni olib tashlang.")
    if audience.get("mode") == "roles" and not audience.get("roles"):
        raise ValueError("Kamida bitta rolni tanlang")
    if audience.get("mode") == "users" and not audience.get("users"):
        raise ValueError("Kamida bitta xodimni tanlang")
    if not await c.db.audience_users(audience):
        raise ValueError("Tanlangan auditoriyada tasdiqlangan xodim yo'q")
    file_id = None
    draft = {"kind": kind, "title": title, "text": text, "author": author, "ack_required": ack_required, "id": 0}
    if image:
        try:
            sent = await c.bot.send_photo(admin_id, BufferedInputFile(image, filename=filename or "image.jpg"),
                                          caption=render(draft), parse_mode="HTML")
        except TelegramAPIError as exc:
            raise ValueError(f"Rasmni Telegramga yuklab bo'lmadi: {exc}") from exc
        file_id = sent.photo[-1].file_id
    ann_id = await c.db.add_announcement(kind, title or None, text or None, file_id, audience, ack_required, author)
    if not image:
        try:
            draft["id"] = ann_id
            await c.bot.send_message(admin_id, "👁 <i>Oldindan ko'rish</i>\n\n" + render(draft), parse_mode="HTML",
                                     reply_markup=keyboard(draft))
        except TelegramAPIError:
            pass  # Telegramdagi ko'rinish shart emas, panelda ham ko'rinadi
    return ann_id


def to_utc(local_value: str, tz_name: str) -> str | None:
    """'2026-09-30T09:00' (mahalliy vaqt) -> 'YYYY-MM-DD HH:MM:SS' (UTC)."""
    try:
        dt = datetime.strptime(local_value.strip(), "%Y-%m-%dT%H:%M").replace(tzinfo=ZoneInfo(tz_name))
    except ValueError:
        return None
    return dt.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M:%S")


async def schedule(ann_id: int, when_utc: str) -> bool:
    return await get_ctx().db.claim_announcement(ann_id, ("draft", "scheduled"), "scheduled", when_utc)


async def unschedule(ann_id: int) -> bool:
    return await get_ctx().db.claim_announcement(ann_id, ("scheduled",), "draft", None)


async def start(ann_id: int) -> bool:
    """Yuborishni boshlaydi (fon vazifasi). Ikki marta boshlanmaydi."""
    c = get_ctx()
    if not await c.db.claim_announcement(ann_id, ("draft", "scheduled"), "sending"):
        return False
    ann = await c.db.get_announcement(ann_id)
    users = await c.db.audience_users(ann["aud"])
    await c.db.add_recipients(ann_id, [u["id"] for u in users])
    _spawn(ann_id)
    return True


def _spawn(ann_id: int) -> None:
    t = _tasks.get(ann_id)
    if t and not t.done():
        return
    _tasks[ann_id] = asyncio.create_task(deliver(ann_id))


async def deliver(ann_id: int) -> None:
    c = get_ctx()
    try:
        ann = await c.db.get_announcement(ann_id)
        if not ann:
            return
        for r in await c.db.pending_recipients(ann_id):
            for attempt in range(3):
                try:
                    mid = await _send_one(r["tg_id"], ann)
                    await c.db.mark_recipient(ann_id, r["user_id"], "sent", mid)
                    break
                except TelegramRetryAfter as exc:
                    await asyncio.sleep(min(exc.retry_after, 30) + 1)
                    continue
                except TelegramForbiddenError:
                    await c.db.mark_recipient(ann_id, r["user_id"], "failed", error="Botni bloklagan")
                    break
                except TelegramAPIError as exc:
                    await c.db.mark_recipient(ann_id, r["user_id"], "failed", error=str(exc)[:200])
                    break
            else:
                await c.db.mark_recipient(ann_id, r["user_id"], "failed", error="Telegram limiti")
            await asyncio.sleep(SEND_DELAY)
        await c.db.finish_announcement(ann_id)
        st = await c.db.announcement_stats(ann_id)
        await c.hub.broadcast({"type": "announcement", "id": ann_id})
        from .services import notify_admins

        await notify_admins(f"📢 E'lon yuborildi: {st['sent']}/{st['total']} ta xodimga yetdi"
                            + (f", {st['failed']} tasiga yetmadi" if st["failed"] else "")
                            + f".\n🔗 {c.settings.base_url}/announcements/{ann_id}")
    except Exception:  # noqa: BLE001
        log.exception("E'lonni yuborishda xato (id=%s)", ann_id)
    finally:
        _tasks.pop(ann_id, None)


async def tick() -> int:
    """Har daqiqada: vaqti kelgan e'lonlarni yuboradi, uzilib qolganlarini davom ettiradi."""
    c = get_ctx()
    now = datetime.now(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M:%S")
    n = 0
    for a in await c.db.due_announcements(now):
        if a["status"] == "scheduled":
            if await start(a["id"]):
                n += 1
        elif a["id"] not in _tasks:
            _spawn(a["id"])
    return n


async def wait_all() -> None:
    """Testlar uchun: yuborish tugaguncha kutadi."""
    while _tasks:
        await asyncio.gather(*list(_tasks.values()), return_exceptions=True)


async def acknowledge(ann_id: int, user_id: int) -> bool:
    return await get_ctx().db.ack_announcement(ann_id, user_id)
