"""Tizim holati: xatolar jurnali, AI sarfi va xarajat, salomatlik tekshiruvi."""
from __future__ import annotations

import asyncio
import logging
import time
import traceback
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .context import get_ctx

log = logging.getLogger(__name__)

STARTED = time.time()
scheduler = None            # main.py o'rnatadi
_consec_fail = 0
_last_fail_alert = 0.0
_tasks: set[asyncio.Task] = set()


def _utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def tz_offset_min() -> int:
    off = datetime.now(ZoneInfo(get_ctx().settings.timezone)).utcoffset()
    return int(off.total_seconds() // 60) if off else 0


def day_start_utc(days_back: int = 0) -> str:
    """Mahalliy vaqt bo'yicha `days_back` kun oldingi 00:00 (UTC satri)."""
    tz = ZoneInfo(get_ctx().settings.timezone)
    d = (datetime.now(tz) - timedelta(days=days_back)).replace(hour=0, minute=0, second=0, microsecond=0)
    return _utc(d)


def month_start_utc() -> str:
    tz = ZoneInfo(get_ctx().settings.timezone)
    d = datetime.now(tz).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return _utc(d)


def month_key() -> str:
    return datetime.now(ZoneInfo(get_ctx().settings.timezone)).strftime("%Y-%m")


# ------------------------------------------------------------------ xatolar jurnali
class DBLogHandler(logging.Handler):
    """ERROR va undan yuqori darajadagi loglarni bazaga yozadi (panelda "Tizim holati" sahifasida ko'rinadi)."""

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith(("aiosqlite", "app.ops")):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        detail = None
        if record.exc_info:
            detail = "".join(traceback.format_exception(*record.exc_info))[-3500:]
        msg = record.getMessage()
        task = loop.create_task(_save_error(record.name, msg, detail))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)


async def _save_error(source: str, msg: str, detail: str | None) -> None:
    try:
        await get_ctx().db.add_error(source, msg, detail)
    except Exception:  # noqa: BLE001
        pass


def install_error_log() -> None:
    root = logging.getLogger()
    if not any(isinstance(h, DBLogHandler) for h in root.handlers):
        h = DBLogHandler(level=logging.ERROR)
        root.addHandler(h)


# ------------------------------------------------------------------ narx va limit sozlamalari
async def get_prices() -> dict[str, float]:
    db = get_ctx().db
    out = {}
    for key in ("price_in", "price_out", "budget_month"):
        try:
            out[key] = float((await db.get_kv(key, "0") or "0").replace(",", "."))
        except ValueError:
            out[key] = 0.0
    return out


def cost(tin: int, tout: int, prices: dict[str, float]) -> float:
    return tin / 1_000_000 * prices.get("price_in", 0) + tout / 1_000_000 * prices.get("price_out", 0)


async def record_usage(purpose: str, model: str | None, tin: int, tout: int, ok: bool = True,
                       error: str | None = None) -> None:
    """Har bir OpenAI so'rovini yozadi; ketma-ket xatolar va oylik limit haqida adminlarga xabar beradi."""
    global _consec_fail, _last_fail_alert
    try:
        c = get_ctx()
        await c.db.add_usage(purpose, model, tin, tout, ok, error)
        if ok:
            _consec_fail = 0
            await _check_budget()
            return
        _consec_fail += 1
        if _consec_fail >= 3 and time.time() - _last_fail_alert > 1800:
            _last_fail_alert = time.time()
            from .services import notify_admins

            await notify_admins("⚠️ OpenAI ketma-ket xato bermoqda (" + str(_consec_fail) + " marta). "
                                f"Oxirgi xato: {(error or '')[:150]}\n🔗 {c.settings.base_url}/system")
    except Exception:  # noqa: BLE001
        log.debug("Sarfni yozib bo'lmadi", exc_info=True)


async def _check_budget() -> None:
    c = get_ctx()
    prices = await get_prices()
    limit = prices["budget_month"]
    if limit <= 0 or (prices["price_in"] <= 0 and prices["price_out"] <= 0):
        return
    s = await c.db.usage_sum(month_start_utc())
    spent = cost(s["tin"], s["tout"], prices)
    mk = month_key()
    from .services import notify_admins

    for pct, key in ((100, "budget_alert100"), (80, "budget_alert80")):
        if spent >= limit * pct / 100:
            if await c.db.get_kv(key) == mk:
                return
            await c.db.set_kv(key, mk)
            if pct == 80:
                await c.db.set_kv("budget_alert80", mk)
            await notify_admins(f"💰 AI xarajati oylik limitning {pct}% ga yetdi: ${spent:.2f} / ${limit:.2f}.\n"
                                f"🔗 {c.settings.base_url}/usage")
            return


# ------------------------------------------------------------------ salomatlik
def uptime_text() -> str:
    sec = int(time.time() - STARTED)
    d, r = divmod(sec, 86400)
    h, r = divmod(r, 3600)
    m = r // 60
    return (f"{d} kun " if d else "") + f"{h} soat {m} daq."


async def run_checks() -> list[dict]:
    """Telegram, OpenAI va bazani tekshiradi. [{name, ok, detail}]"""
    c = get_ctx()
    out = []
    try:
        me = await c.bot.get_me()
        out.append({"name": "Telegram bot", "ok": True, "detail": f"@{getattr(me, 'username', '')} ulangan"})
    except Exception as exc:  # noqa: BLE001
        out.append({"name": "Telegram bot", "ok": False, "detail": str(exc)[:200]})
    try:
        await c.agent.ping()
        out.append({"name": "OpenAI va bilimlar bazasi (vector store)", "ok": True, "detail": "Ulanish ishlayapti"})
    except Exception as exc:  # noqa: BLE001
        out.append({"name": "OpenAI va bilimlar bazasi (vector store)", "ok": False, "detail": str(exc)[:200]})
    try:
        await c.db._one("SELECT 1 c")
        size = c.settings.db_file.stat().st_size / 1024 / 1024 if c.settings.db_file.exists() else 0
        out.append({"name": "Ma'lumotlar bazasi", "ok": True, "detail": f"Ishlayapti ({size:.1f} MB)"})
    except Exception as exc:  # noqa: BLE001
        out.append({"name": "Ma'lumotlar bazasi", "ok": False, "detail": str(exc)[:200]})
    return out


def scheduler_jobs() -> list[dict]:
    jobs = []
    if scheduler is not None:
        for j in scheduler.get_jobs():
            nrt = getattr(j, "next_run_time", None)
            jobs.append({"id": j.id, "next": nrt.astimezone(ZoneInfo(get_ctx().settings.timezone)).strftime("%d.%m %H:%M")
                         if nrt else "—"})
    return sorted(jobs, key=lambda j: j["id"])
