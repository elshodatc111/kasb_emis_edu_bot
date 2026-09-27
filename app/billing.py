"""OpenAI tashkilotidagi HAQIQIY kunlik xarajat (Admin API orqali). Token sarflamaydi, alohida OPENAI_ADMIN_KEY talab qiladi.

OpenAI hozircha "qoldiq balans"ni ochiq API orqali bermaydi (faqat platform.openai.com boshqaruv panelida ko'rinadi),
shuning uchun balansni admin bir marta panelda kiritadi, undan keyin har kunlik REAL xarajat (Costs API) ayirib boriladi.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import httpx

from .context import get_ctx

log = logging.getLogger(__name__)

BASE = "https://api.openai.com/v1/organization"
CACHE_SECONDS = 300
_cache: dict[str, tuple[float, dict]] = {}


async def _get(path: str, params: dict) -> dict:
    key = get_ctx().settings.openai_admin_key
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(f"{BASE}{path}", params=params, headers={"Authorization": f"Bearer {key}"})
    if r.status_code == 401:
        raise RuntimeError("OPENAI_ADMIN_KEY noto'g'ri yoki muddati o'tgan")
    if r.status_code == 403:
        raise RuntimeError("Bu kalitda xarajatlarni ko'rish huquqi yo'q (oddiy API key emas, Admin key kerak)")
    if r.status_code == 404:
        raise RuntimeError("Bu tashkilotda xarajat API topilmadi")
    r.raise_for_status()
    return r.json()


async def _paged(path: str, start: int, end: int, limit: int) -> list[dict]:
    out: list[dict] = []
    page = None
    for _ in range(40):  # cheksiz aylanishdan saqlanish uchun chegara
        params: dict = {"start_time": start, "end_time": end, "bucket_width": "1d", "limit": limit}
        if page:
            params["page"] = page
        data = await _get(path, params)
        out += data.get("data", [])
        page = data.get("next_page")
        if not page:
            break
    return out


def _day(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def _cost_days(buckets: list[dict]) -> list[dict]:
    return [{"day": _day(b["start_time"]),
             "usd": sum((r.get("amount") or {}).get("value") or 0 for r in b.get("results", []))}
            for b in buckets]


def _usage_days(buckets: list[dict]) -> list[dict]:
    out = []
    for b in buckets:
        rs = b.get("results", [])
        out.append({"day": _day(b["start_time"]),
                    "tin": sum(r.get("input_tokens") or 0 for r in rs),
                    "tout": sum(r.get("output_tokens") or 0 for r in rs),
                    "requests": sum(r.get("num_model_requests") or 0 for r in rs)})
    return out


async def fetch(days: int = 30) -> dict:
    """Oxirgi `days` kunlik haqiqiy xarajat (USD) va tokenlar. 5 daqiqa keshlanadi.

    Natija: {"available": True, "days_cost": [...], "days_usage": [...]}
         yoki {"available": False, "reason": "no_key" | "error", "error": "..."}
    """
    settings = get_ctx().settings
    if not settings.openai_admin_key:
        return {"available": False, "reason": "no_key"}
    days = max(1, min(180, days))
    cache_key = f"{settings.openai_admin_key[-8:]}:{days}"
    hit = _cache.get(cache_key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    end = int(time.time())
    start = end - days * 86400
    try:
        cost_buckets = await _paged("/costs", start, end, limit=180)
        # usage/completions bucket_width=1d uchun OpenAI eng ko'pi bilan 31 tani qaytaradi (180 yuborilsa 400 beradi)
        usage_buckets = await _paged("/usage/completions", start, end, limit=31)
    except Exception as exc:  # noqa: BLE001
        log.warning("OpenAI xarajat API xato berdi: %s", exc)
        try:
            await get_ctx().db.add_error("openai_billing", str(exc)[:200])
        except Exception:  # noqa: BLE001
            pass
        result = {"available": False, "reason": "error", "error": str(exc)[:200]}
        _cache[cache_key] = (time.time(), result)
        return result
    result = {"available": True, "days_cost": _cost_days(cost_buckets), "days_usage": _usage_days(usage_buckets)}
    _cache[cache_key] = (time.time(), result)
    return result


def sum_cost_since(days_cost: list[dict], since_day: str) -> float:
    return sum(d["usd"] for d in days_cost if d["day"] >= since_day)


def clear_cache() -> None:
    _cache.clear()
