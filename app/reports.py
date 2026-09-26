"""Kunlik / haftalik / oylik hisobotlar va video reja generatsiyasi."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import services
from .agent import AgentError
from .context import get_ctx
from .db import FMT
from .privacy import mask_sensitive

log = logging.getLogger(__name__)

KIND_UZ = {"daily": "Kunlik", "weekly": "Haftalik", "monthly": "Oylik"}


def _to_utc_str(dt_local: datetime) -> str:
    return dt_local.astimezone(timezone.utc).strftime(FMT)


def period_for(kind: str, tz_name: str, now: datetime | None = None, scheduled: bool = False):
    """(start_utc_str, end_utc_str, label) qaytaradi. Vaqt oralig'i mahalliy (Toshkent) vaqt bo'yicha."""
    tz = ZoneInfo(tz_name)
    now_l = (now or datetime.now(timezone.utc)).astimezone(tz)
    today0 = now_l.replace(hour=0, minute=0, second=0, microsecond=0)
    end = now_l + timedelta(seconds=1)  # hozirgi lahzani ham qamrab olish uchun
    if kind == "daily":
        start = today0
        label = f"{today0:%Y-%m-%d} (bugun)"
    elif kind == "weekly":
        start = today0 - timedelta(days=6)
        label = f"{start:%Y-%m-%d} - {now_l:%Y-%m-%d} (oxirgi 7 kun)"
    elif kind == "monthly":
        if scheduled:  # har oyning 1-sanasida o'tgan oy uchun
            end = today0.replace(day=1)
            start = (end - timedelta(days=1)).replace(day=1)
            label = f"{start:%Y-%m} (o'tgan oy)"
        else:
            start = today0.replace(day=1)
            label = f"{start:%Y-%m-%d} - {now_l:%Y-%m-%d} (joriy oy)"
    else:
        raise ValueError(f"Noma'lum hisobot turi: {kind}")
    return _to_utc_str(start), _to_utc_str(end), label


def _fallback_markdown(stats: dict, label: str, note: str) -> str:
    lines = [f"## Ko'rsatkichlar ({label})", "",
             f"- Savollar: {stats['questions']} (javob berildi: {stats['answered']}, javobsiz: {stats['unanswered']})",
             f"- Faol foydalanuvchilar: {stats['active_users']}",
             f"- Rasmlar: {stats['photos']}, qabul qilinmagan kontent: {stats['other_media']}",
             f"- Admin xabarlari: {stats['admin_messages']}",
             ""]
    if stats["by_topic"]:
        lines.append("## Mavzular")
        lines += [f"- {t['topic']}: {t['n']} (javobsiz: {t['unanswered'] or 0})" for t in stats["by_topic"][:10]]
    lines += ["", f"_{note}_"]
    return "\n".join(lines)


async def _samples(start: str, end: str, by_topic: list[dict]) -> dict:
    c = get_ctx()
    samples: dict[str, list[str]] = {}
    for t in by_topic[:5]:
        qs = await c.db.period_questions(start, end, topic=t["topic"], limit=5)
        samples[t["topic"]] = [mask_sensitive(q["text"])[0][:300] for q in qs]
    un = await c.db.period_questions(start, end, only_unanswered=True, limit=15)
    samples["Javobsiz savollar"] = [mask_sensitive(q["text"])[0][:300] for q in un]
    return samples


async def generate_report(kind: str, scheduled: bool = False, notify: bool = False) -> int:
    c = get_ctx()
    start, end, label = period_for(kind, c.settings.timezone, scheduled=scheduled)
    tz = ZoneInfo(c.settings.timezone)
    offset = int((datetime.now(timezone.utc).astimezone(tz).utcoffset() or timedelta()).total_seconds() // 60)
    stats = await c.db.period_stats(start, end, tz_offset_min=offset)
    # oldingi shunday davr bilan solishtirish uchun
    s_dt = datetime.strptime(start, FMT)
    e_dt = datetime.strptime(end, FMT)
    prev_start = (s_dt - (e_dt - s_dt)).strftime(FMT)
    prev = await c.db.period_stats(prev_start, start)
    stats["prev_questions"] = prev["questions"]
    stats["label"] = label
    if stats["questions"] == 0 and stats["photos"] == 0 and stats["new_requests"] == 0:
        content = f"## {label}\n\nBu davrda savollar va yangi so'rovlar bo'lmadi."
    else:
        try:
            samples = await _samples(start, end, stats["by_topic"])
            content = await c.agent.report_summary(label, stats, samples)
        except AgentError as exc:
            log.warning("Hisobot xulosasini AI yozib bermadi: %s", exc)
            content = _fallback_markdown(stats, label, "AI xulosa yozib bera olmadi, faqat raqamlar ko'rsatildi.")
    rid = await c.db.add_report(kind, start, end, stats, content)
    if notify:
        await services.notify_admins(
            f"{KIND_UZ[kind]} hisobot tayyor ({label})\n"
            f"Savollar: {stats['questions']} (javobsiz: {stats['unanswered']}), faol foydalanuvchilar: {stats['active_users']}, "
            f"rasmlar: {stats['photos']}\nBatafsil: {c.settings.base_url}/reports/{rid}")
    return rid


async def generate_video_plans(start: str, end: str, top_n: int = 3, min_questions: int = 2) -> list[int]:
    """Davr ichida eng ko'p (va javobsiz) so'ralgan mavzular bo'yicha video rolik rejalarini yaratadi."""
    c = get_ctx()
    stats = await c.db.period_stats(start, end)
    topics = [t for t in stats["by_topic"] if t["n"] >= min_questions and t["topic"] != "Boshqa"]
    topics.sort(key=lambda t: t["n"] + 2 * (t["unanswered"] or 0), reverse=True)
    ids: list[int] = []
    for t in topics[:top_n]:
        qs = await c.db.period_questions(start, end, topic=t["topic"], limit=25)
        for q in qs:
            q["text"] = mask_sensitive(q["text"])[0]
            if q.get("bot_answer"):
                q["bot_answer"] = mask_sensitive(q["bot_answer"])[0]
        roles: dict[str, int] = {}
        for q in qs:
            roles[q["role"] or "Noma'lum"] = roles.get(q["role"] or "Noma'lum", 0) + 1
        main_role = max(roles, key=roles.get) if roles else None
        try:
            md = await c.agent.video_plan(t["topic"], sorted(roles, key=roles.get, reverse=True), qs)
        except AgentError as exc:
            log.warning("Video reja yaratilmadi (%s): %s", t["topic"], exc)
            continue
        m = re.search(r"^#\s*(?:Video rolik:)?\s*(.+)$", md, flags=re.M)
        title = (m.group(1).strip() if m else f"{t['topic']} bo'yicha video rolik")[:150]
        ids.append(await c.db.add_video_plan(title, t["topic"], main_role, t["n"], md, start, end))
    return ids
