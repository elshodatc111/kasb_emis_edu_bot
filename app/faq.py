"""FAQ: kelgan savollarni tahlil qilib, ko'p so'raladigan savollarni AI yordamida yig'adi (admin tasdiqlaydi)."""
from __future__ import annotations

import logging
from datetime import timedelta

from . import services
from .agent import AgentError
from .constants import TOPICS
from .context import get_ctx
from .db import FMT, utcnow
from .kb import tokens
from .privacy import mask_sensitive

log = logging.getLogger(__name__)
MIN_ITEMS = 4


def _similar(a: str, b: str) -> bool:
    ta, tb = tokens(a), tokens(b)
    return bool(ta and tb) and len(ta & tb) / max(1, min(len(ta), len(tb))) >= 0.8


async def analyze(notify: bool = True) -> dict:
    """So'nggi FAQ_DAYS kundagi savollarni tahlil qiladi. Yangi variantlar 'pending' holatida saqlanadi."""
    c = get_ctx()
    end = utcnow() + timedelta(minutes=1)
    start = end - timedelta(days=c.settings.faq_days)
    rows = await c.db.period_questions(start.strftime(FMT), end.strftime(FMT), limit=300)
    items = []
    for r in rows:
        if r.get("found") != 1 or not r.get("bot_answer"):
            continue
        items.append({"savol": mask_sensitive(r["text"])[0][:250], "javob": mask_sensitive(r["bot_answer"])[0][:600],
                      "mavzu": r.get("topic") or "Boshqa"})
    if len(items) < MIN_ITEMS:
        return {"created": 0, "updated": 0, "reason": "few"}
    existing_rows = await c.db.list_faq()
    existing = [{"id": e["id"], "question": e["question"]} for e in existing_rows]
    try:
        clusters = await c.agent.faq_clusters(items[:120], existing[:80])
    except AgentError as exc:
        log.warning("FAQ tahlili xato berdi: %s", exc)
        return {"created": 0, "updated": 0, "reason": "error", "error": str(exc)[:200]}
    by_id = {e["id"]: e for e in existing_rows}
    created = updated = 0
    for cl in clusters:
        q = mask_sensitive(str(cl.get("question") or "").strip())[0]
        a = mask_sensitive(str(cl.get("answer") or "").strip())[0]
        try:
            count = int(cl.get("count") or 0)
        except (TypeError, ValueError):
            count = 0
        mid = cl.get("match_id")
        if isinstance(mid, int) and mid in by_id:
            await c.db.set_faq_count(mid, count)
            updated += 1
            continue
        if not q or not a or any(_similar(q, e["question"]) for e in existing_rows):
            continue
        topic = cl.get("topic") if cl.get("topic") in TOPICS else "Boshqa"
        fid = await c.db.add_faq(q, a, topic, "pending", count)
        existing_rows.append({"id": fid, "question": q})
        created += 1
    if created and notify:
        await services.notify_admins(f"FAQ uchun {created} ta yangi variant tayyor. Ko'rib chiqing: {c.settings.base_url}/faq")
    await services.push({"type": "faq"})
    return {"created": created, "updated": updated, "reason": "ok"}
