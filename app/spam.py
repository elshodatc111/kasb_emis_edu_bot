"""Spamdan himoya: bir xil savol qayta-qayta yuborilsa AI chaqirilmaydi, juda ko'p urinsa vaqtincha to'xtatiladi."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

WINDOW = 600        # soniya: shu vaqt ichidagi takror "bir xil savol" hisoblanadi
MAX_ASKS = 4        # 4-marta yuborilganda vaqtincha to'xtatiladi
MUTE_SECONDS = 900  # 15 daqiqa

_recent: dict[int, dict[str, dict]] = {}
_muted: dict[int, float] = {}
_mute_told: set[int] = set()


@dataclass
class Verdict:
    kind: str            # new | repeat | mute
    reply: str | None = None
    count: int = 1


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9а-яё]+", " ", text.lower().replace("‘", "'").replace("’", "'").replace("`", "'")).strip()


def muted_left(user_id: int) -> int:
    """To'xtatilgan bo'lsa qolgan soniyalar, aks holda 0."""
    until = _muted.get(user_id, 0)
    left = int(until - time.monotonic())
    if left <= 0:
        _muted.pop(user_id, None)
        _mute_told.discard(user_id)
        return 0
    return left


def told_mute(user_id: int) -> bool:
    """Foydalanuvchiga to'xtatilgani haqida faqat bir marta xabar beriladi."""
    if user_id in _mute_told:
        return True
    _mute_told.add(user_id)
    return False


def check(user_id: int, text: str) -> Verdict:
    now = time.monotonic()
    key = norm(text)
    if not key:
        return Verdict("new")
    per_user = _recent.setdefault(user_id, {})
    for k in [k for k, v in per_user.items() if now - v["ts"] > WINDOW]:
        per_user.pop(k, None)
    e = per_user.get(key)
    if not e or not e.get("reply"):
        per_user[key] = {"ts": now, "count": 1, "reply": None}
        return Verdict("new")
    e["count"] += 1
    if e["count"] >= MAX_ASKS:
        _muted[user_id] = now + MUTE_SECONDS
        _mute_told.discard(user_id)
        per_user.pop(key, None)
        return Verdict("mute", count=e["count"])
    return Verdict("repeat", reply=e["reply"], count=e["count"])


def remember(user_id: int, text: str, reply_html: str) -> None:
    key = norm(text)
    e = _recent.get(user_id, {}).get(key)
    if e is not None:
        e["reply"] = reply_html


def unmute(user_id: int) -> None:
    _muted.pop(user_id, None)
    _mute_told.discard(user_id)


def muted_users() -> list[tuple[int, int]]:
    now = time.monotonic()
    return [(uid, int(t - now)) for uid, t in _muted.items() if t > now]


def clear() -> None:
    _recent.clear()
    _muted.clear()
    _mute_told.clear()
