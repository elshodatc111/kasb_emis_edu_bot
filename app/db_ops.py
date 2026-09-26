"""Tizim boshqaruvi jadvallari: xatolar jurnali, AI sarfi, ichki izohlar, spam, bayramlar, qidiruv, reset."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


OPS_SCHEMA = """
CREATE TABLE IF NOT EXISTS error_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    message TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_error_created ON error_log(created_at);
CREATE TABLE IF NOT EXISTS ai_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    purpose TEXT NOT NULL,
    model TEXT,
    tokens_in INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    ok INTEGER NOT NULL DEFAULT 1,
    error TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usage_created ON ai_usage(created_at);
CREATE TABLE IF NOT EXISTS user_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    author TEXT,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS spam_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    kind TEXT NOT NULL,                          -- repeat | muted
    text TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS holidays (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,                           -- YYYY-MM-DD yoki (takrorlanuvchi) MM-DD
    name TEXT NOT NULL,
    recurring INTEGER NOT NULL DEFAULT 0
);
"""

DEFAULT_HOLIDAYS = [
    ("01-01", "Yangi yil"),
    ("03-08", "Xalqaro xotin-qizlar kuni"),
    ("03-21", "Navro'z bayrami"),
    ("05-09", "Xotira va qadrlash kuni"),
    ("09-01", "Mustaqillik kuni"),
    ("10-01", "O'qituvchi va murabbiylar kuni"),
    ("12-08", "Konstitutsiya kuni"),
]

# reset o'chiradigan jadvallar (foydalanuvchilar, bilimlar bazasi, FAQ (tasdiqlangan), video kutubxona, shablonlar qoladi)
RESET_TABLES = [
    ("messages", "Yozishmalar (xabarlar)"),
    ("quiz_sessions", "Viktorina sessiyalari"),
    ("quiz_answers", "Viktorina javoblari"),
    ("quiz_assigned", "Viktorinada berilgan savollar tarixi"),
    ("announcements", "E'lonlar"),
    ("announcement_recipients", "E'lon yetkazish hisoboti"),
    ("reports", "Hisobotlar"),
    ("video_plans", "Video rejalar"),
    ("user_notes", "Ichki izohlar"),
    ("spam_events", "Spam jurnali"),
    ("ai_usage", "AI sarfi tarixi"),
    ("error_log", "Xatolar jurnali"),
]


class OpsMixin:
    # ---------- xatolar ----------
    async def add_error(self, source: str, message: str, detail: str | None = None) -> None:
        await self._exec("INSERT INTO error_log (source, message, detail, created_at) VALUES (?,?,?,?)",
                         (source[:60], message[:500], (detail or "")[:4000] or None, _ts()))
        await self._exec("DELETE FROM error_log WHERE id NOT IN (SELECT id FROM error_log ORDER BY id DESC LIMIT 500)")

    async def list_errors(self, limit: int = 50) -> list[dict]:
        return await self._all("SELECT * FROM error_log ORDER BY id DESC LIMIT ?", (limit,))

    async def count_errors(self, since: str) -> int:
        r = await self._one("SELECT COUNT(*) c FROM error_log WHERE created_at>=?", (since,))
        return int((r or {}).get("c", 0))

    async def clear_errors(self) -> None:
        await self._exec("DELETE FROM error_log")

    # ---------- AI sarfi ----------
    async def add_usage(self, purpose: str, model: str | None, tin: int, tout: int, ok: bool = True,
                        error: str | None = None) -> None:
        await self._exec("INSERT INTO ai_usage (purpose, model, tokens_in, tokens_out, ok, error, created_at)"
                         " VALUES (?,?,?,?,?,?,?)", (purpose, model, tin, tout, int(ok), (error or "")[:300] or None, _ts()))

    async def usage_sum(self, since: str, until: str | None = None) -> dict[str, int]:
        until = until or "9999-12-31 00:00:00"
        r = await self._one(
            "SELECT COUNT(*) requests, COALESCE(SUM(tokens_in),0) tin, COALESCE(SUM(tokens_out),0) tout,"
            " COALESCE(SUM(1-ok),0) errors FROM ai_usage WHERE created_at>=? AND created_at<?", (since, until))
        return {k: int(v or 0) for k, v in (r or {}).items()}

    async def usage_by_purpose(self, since: str) -> list[dict]:
        return await self._all(
            "SELECT purpose, COUNT(*) requests, COALESCE(SUM(tokens_in),0) tin, COALESCE(SUM(tokens_out),0) tout,"
            " COALESCE(SUM(1-ok),0) errors FROM ai_usage WHERE created_at>=? GROUP BY purpose ORDER BY tin+tout DESC",
            (since,))

    async def usage_by_day(self, since: str, tz_offset_min: int) -> list[dict]:
        return await self._all(
            "SELECT date(created_at, ?) day, COUNT(*) requests, COALESCE(SUM(tokens_in),0) tin,"
            " COALESCE(SUM(tokens_out),0) tout FROM ai_usage WHERE created_at>=? GROUP BY day ORDER BY day",
            (f"{tz_offset_min:+d} minutes", since))

    async def last_usage(self, ok: bool) -> dict | None:
        return await self._one("SELECT * FROM ai_usage WHERE ok=? ORDER BY id DESC LIMIT 1", (int(ok),))

    # ---------- ichki izohlar ----------
    async def add_note(self, user_id: int, author: str, text: str) -> int:
        return await self._exec("INSERT INTO user_notes (user_id, author, text, created_at) VALUES (?,?,?,?)",
                                (user_id, author, text, _ts()))

    async def list_notes(self, user_id: int) -> list[dict]:
        return await self._all("SELECT * FROM user_notes WHERE user_id=? ORDER BY id DESC", (user_id,))

    async def delete_note(self, note_id: int) -> None:
        await self._exec("DELETE FROM user_notes WHERE id=?", (note_id,))

    async def note_counts(self) -> dict[int, int]:
        rows = await self._all("SELECT user_id, COUNT(*) n FROM user_notes GROUP BY user_id")
        return {r["user_id"]: r["n"] for r in rows}

    # ---------- spam ----------
    async def add_spam(self, user_id: int, kind: str, text: str | None) -> None:
        await self._exec("INSERT INTO spam_events (user_id, kind, text, created_at) VALUES (?,?,?,?)",
                         (user_id, kind, (text or "")[:200], _ts()))

    async def list_spam(self, limit: int = 30) -> list[dict]:
        return await self._all(
            "SELECT s.*, u.full_name, u.role FROM spam_events s LEFT JOIN users u ON u.id=s.user_id"
            " ORDER BY s.id DESC LIMIT ?", (limit,))

    # ---------- bayramlar ----------
    async def list_holidays(self) -> list[dict]:
        return await self._all("SELECT * FROM holidays ORDER BY recurring DESC, day")

    async def add_holiday(self, day: str, name: str, recurring: bool) -> int:
        return await self._exec("INSERT INTO holidays (day, name, recurring) VALUES (?,?,?)", (day, name, int(recurring)))

    async def delete_holiday(self, hid: int) -> None:
        await self._exec("DELETE FROM holidays WHERE id=?", (hid,))

    async def seed_holidays(self) -> None:
        if await self.get_kv("holidays_seeded"):
            return
        for day, name in DEFAULT_HOLIDAYS:
            await self.add_holiday(day, name, True)
        await self.set_kv("holidays_seeded", "1")

    # ---------- suhbatni biriktirish ----------
    async def assign_chat(self, user_id: int, admin_id: int | None) -> None:
        await self._exec("UPDATE users SET assigned_to=?, assigned_at=? WHERE id=?",
                         (admin_id, _ts() if admin_id else None, user_id))

    # ---------- qidiruv ----------
    async def search_messages(self, q: str, sender: str = "", limit: int = 100) -> list[dict]:
        like = "%" + q.strip().replace("%", r"\%").replace("_", r"\_") + "%"
        sql = ("SELECT m.id, m.user_id, m.sender, m.kind, m.text, m.author, m.created_at, u.full_name, u.role, u.tech_name"
               " FROM messages m JOIN users u ON u.id=m.user_id WHERE m.text LIKE ? ESCAPE '\\'")
        params: list[Any] = [like]
        if sender in ("user", "bot", "admin"):
            sql += " AND m.sender=?"
            params.append(sender)
        sql += " ORDER BY m.id DESC LIMIT ?"
        params.append(limit)
        return await self._all(sql, params)

    # ---------- faol bo'lmagan xodimlar ----------
    async def inactive_users(self, days: int) -> list[dict]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        rows = await self._all(
            "SELECT u.*, (SELECT MAX(created_at) FROM messages m WHERE m.user_id=u.id AND m.sender='user') AS last_msg,"
            " (SELECT MAX(answered_at) FROM quiz_answers a WHERE a.user_id=u.id) AS last_quiz"
            " FROM users u WHERE u.status='approved'")
        out = []
        for r in rows:
            cands = [x for x in (r["last_msg"], r["last_quiz"]) if x]
            r["last_active"] = max(cands) if cands else None
            base = r["last_active"] or r.get("approved_at") or r.get("created_at") or ""
            if base < cutoff:
                out.append(r)
        out.sort(key=lambda r: r["last_active"] or "")
        return out

    # ---------- reset ----------
    async def reset_preview(self) -> list[tuple[str, int]]:
        out = []
        for table, label in RESET_TABLES:
            r = await self._one(f"SELECT COUNT(*) c FROM {table}")
            out.append((label, int((r or {}).get("c", 0))))
        r = await self._one("SELECT COUNT(*) c FROM faq_items WHERE status='pending'")
        out.append(("Tasdiqlanmagan FAQ takliflari", int((r or {}).get("c", 0))))
        return out

    async def reset_data(self) -> int:
        """Yozishmalar va ular bilan bog'liq ma'lumotlarni o'chiradi. Foydalanuvchilar, bilimlar bazasi, tasdiqlangan FAQ,
        video kutubxona, shablonlar, viktorina savollari va sozlamalar qoladi. O'chirilgan qatorlar sonini qaytaradi."""
        assert self.conn
        total = sum(n for _l, n in await self.reset_preview())
        for table, _label in RESET_TABLES:
            await self.conn.execute(f"DELETE FROM {table}")
        await self.conn.execute("DELETE FROM faq_items WHERE status='pending'")
        await self.conn.execute("UPDATE kb_entries SET source_msg_id=NULL")
        await self.conn.execute("UPDATE users SET needs_attention=0, unread=0, mode='bot', mode_since=NULL,"
                                " photo_notified_at=NULL, last_message_at=NULL, assigned_to=NULL, assigned_at=NULL")
        await self.conn.execute("DELETE FROM sqlite_sequence WHERE name IN "
                                "('messages','quiz_sessions','quiz_answers','announcements','reports','video_plans',"
                                "'user_notes','spam_events','ai_usage','error_log')")
        await self.conn.commit()
        try:
            await self.conn.execute("VACUUM")
        except Exception:  # noqa: BLE001
            pass
        return total
