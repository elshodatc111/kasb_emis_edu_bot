from __future__ import annotations

import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from . import announce, faq, kb, quiz, reports, services
from .context import get_ctx

log = logging.getLogger(__name__)


async def _safe(coro_fn, *a, **kw):
    try:
        await coro_fn(*a, **kw)
    except Exception:  # noqa: BLE001
        log.exception("Rejalashtirilgan vazifa xato berdi")


async def job_daily():
    await reports.generate_report("daily", notify=True)


async def job_weekly():
    c = get_ctx()
    await reports.generate_report("weekly", notify=True)
    start, end, _ = reports.period_for("weekly", c.settings.timezone)
    ids = await reports.generate_video_plans(start, end)
    if ids:
        await services.notify_admins(f"Haftalik video rolik rejalari tayyor: {len(ids)} ta.\n{c.settings.base_url}/videos")


async def job_monthly():
    await reports.generate_report("monthly", scheduled=True, notify=True)


async def job_remind():
    await services.remind_admins()


async def job_quiz_tick():
    await quiz.tick()


async def job_quiz_prepare():
    if services.local_now().isoweekday() in get_ctx().settings.quiz_days:
        await quiz.prepare_pools()


async def job_faq():
    await faq.analyze(notify=True)


async def job_announce():
    await announce.tick()


async def job_kb_sync():
    await kb.sync_to_vector_store()


def build_scheduler(settings) -> AsyncIOScheduler:
    tz = ZoneInfo(settings.timezone)
    sch = AsyncIOScheduler(timezone=tz)
    dh, dm = settings.daily_time
    wh, wm = settings.weekly_time
    mh, mm = settings.monthly_time
    sch.add_job(_safe, CronTrigger(hour=dh, minute=dm, timezone=tz), args=[job_daily], id="daily",
                misfire_grace_time=3600, coalesce=True)
    sch.add_job(_safe, CronTrigger(day_of_week="sun", hour=wh, minute=wm, timezone=tz), args=[job_weekly], id="weekly",
                misfire_grace_time=3600, coalesce=True)
    sch.add_job(_safe, CronTrigger(day=1, hour=mh, minute=mm, timezone=tz), args=[job_monthly], id="monthly",
                misfire_grace_time=3600, coalesce=True)
    sch.add_job(_safe, CronTrigger(minute=f"*/{settings.remind_every_min}", timezone=tz), args=[job_remind],
                id="remind", misfire_grace_time=300, coalesce=True, max_instances=1)
    sch.add_job(_safe, IntervalTrigger(minutes=quiz.TICK_MIN, timezone=tz), args=[job_quiz_tick], id="quiz_tick",
                misfire_grace_time=120, coalesce=True, max_instances=1)
    qh, qm = settings.quiz_start
    prep = max(0, qh * 60 + qm - 50)
    sch.add_job(_safe, CronTrigger(hour=prep // 60, minute=prep % 60, timezone=tz), args=[job_quiz_prepare],
                id="quiz_prepare", misfire_grace_time=1800, coalesce=True)
    fh, fm = settings.faq_time
    sch.add_job(_safe, CronTrigger(hour=fh, minute=fm, timezone=tz), args=[job_faq], id="faq",
                misfire_grace_time=3600, coalesce=True)
    sch.add_job(_safe, IntervalTrigger(minutes=5, timezone=tz), args=[job_kb_sync], id="kb_sync",
                misfire_grace_time=300, coalesce=True, max_instances=1)
    sch.add_job(_safe, IntervalTrigger(minutes=1, timezone=tz), args=[job_announce], id="announce",
                misfire_grace_time=120, coalesce=True, max_instances=1)
    return sch
