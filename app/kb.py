"""Admin tasdiqlagan savol-javoblar: tezkor lokal qidiruv va OpenAI vector store bilan sinxronlash."""
from __future__ import annotations

import hashlib
import io
import logging
import math
import re

from .context import get_ctx
from .db import ts
from .privacy import mask_sensitive

log = logging.getLogger(__name__)

_WORD = re.compile(r"[a-z0-9]+", re.I)
_STOP = {"qanday", "qaysi", "nima", "uchun", "bilan", "yoki", "kerak", "mumkin", "qilish", "qilinadi", "bo'ladi",
         "boladi", "bormi", "yoqmi", "haqida", "menga", "bizda", "sizda", "qayerda", "qayer", "necha"}
KB_FILENAME = "admin_bilim.txt"


def _norm(text: str) -> str:
    return (text or "").lower().replace("‘", "'").replace("’", "'").replace("ʻ", "'").replace("ʼ", "'").replace("`", "'")


def tokens(text: str) -> set[str]:
    """Oddiy 'stemming': so'zning dastlabki 5 harfi (o'zbek qo'shimchalariga chidamli)."""
    out = set()
    for w in _WORD.findall(_norm(text).replace("'", "")):
        if len(w) >= 3 and w not in _STOP:
            out.add(w[:5])
    return out


def find_relevant(entries: list[dict], question: str, limit: int = 3, min_score: float = 0.34) -> list[dict]:
    qt = tokens(question)
    if not qt:
        return []
    scored = []
    for e in entries:
        et = tokens(e["question"])
        if not et:
            continue
        inter = len(qt & et)
        if not inter:
            continue
        score = inter / math.sqrt(len(qt) * len(et))
        if score >= min_score:
            scored.append((score, e))
    scored.sort(key=lambda x: -x[0])
    return [e for _s, e in scored[:limit]]


def clean_entry(text: str) -> tuple[str, int]:
    """Shaxsiy ma'lumotlarni (PINFL/pasport) maskalaydi."""
    return mask_sensitive((text or "").strip())


def build_kb_text(entries: list[dict]) -> str:
    lines = ["ADMIN TASDIQLAGAN SAVOL-JAVOBLAR", "Bu javoblar rasmiy qo'llanmadan ustun turadi.", ""]
    for e in entries:
        lines += [f"Savol: {e['question']}", f"Javob: {e['answer']}"]
        if e.get("topic"):
            lines.append(f"Mavzu: {e['topic']}")
        lines.append("")
    return "\n".join(lines)


def _vs_api(client):
    return getattr(client, "vector_stores", None) or client.beta.vector_stores


async def sync_to_vector_store() -> str:
    """Faol yozuvlarni bitta matn fayli qilib vector store ga yuklaydi (eskisini almashtiradi). Xato bo'lsa matn qaytaradi."""
    c = get_ctx()
    client = c.agent.client
    if hasattr(client, "_is_fake"):
        return "skipped"
    entries = await c.db.list_kb(active_only=True)
    text = build_kb_text(entries)
    digest = hashlib.sha1(text.encode()).hexdigest()
    old_file = await c.db.get_kv("kb_file_id")
    if digest == await c.db.get_kv("kb_hash") and old_file:
        return "ok"
    vs = c.settings.vector_store_id
    try:
        if not entries:
            new_id = None
        else:
            up = await client.files.create(file=(KB_FILENAME, io.BytesIO(text.encode("utf-8"))), purpose="assistants")
            new_id = up.id
            api = _vs_api(client)
            if hasattr(api.files, "create_and_poll"):
                await api.files.create_and_poll(vector_store_id=vs, file_id=new_id)
            else:
                await api.files.create(vector_store_id=vs, file_id=new_id)
        if old_file:
            try:
                await _vs_api(client).files.delete(old_file, vector_store_id=vs)
            except Exception:  # noqa: BLE001
                log.warning("Eski bilim fayli vector store'dan o'chirilmadi")
            try:
                await client.files.delete(old_file)
            except Exception:  # noqa: BLE001
                pass
        await c.db.set_kv("kb_file_id", new_id or "")
        await c.db.set_kv("kb_hash", digest)
        await c.db.set_kv("kb_sync_error", "")
        await c.db.set_kv("kb_synced_at", ts())
        return "ok"
    except Exception as exc:  # noqa: BLE001
        log.exception("Bilimlar bazasini sinxronlashda xato")
        await c.db.set_kv("kb_sync_error", str(exc)[:300])
        return str(exc)[:300]
