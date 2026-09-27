from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from .db_features import FEATURE_SCHEMA, FeaturesMixin
from .db_ops import OPS_SCHEMA, OpsMixin

FMT = "%Y-%m-%d %H:%M:%S"


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def ts(dt: datetime | None = None) -> str:
    return (dt or utcnow()).strftime(FMT)


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, FMT)
    except ValueError:
        return None


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id INTEGER NOT NULL UNIQUE,
    tg_username TEXT,
    full_name TEXT,
    phone TEXT,
    tech_name TEXT,
    role TEXT,
    status TEXT NOT NULL DEFAULT 'pending',      -- pending | approved | rejected | blocked
    mode TEXT NOT NULL DEFAULT 'bot',            -- bot | admin
    mode_since TEXT,
    needs_attention INTEGER NOT NULL DEFAULT 0,
    unread INTEGER NOT NULL DEFAULT 0,
    photo_notified_at TEXT,
    created_at TEXT NOT NULL,
    approved_at TEXT,
    last_message_at TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    sender TEXT NOT NULL,                        -- user | bot | admin
    kind TEXT NOT NULL DEFAULT 'text',           -- text | photo | video | other
    text TEXT,
    file_id TEXT,                                -- faqat Telegram file_id; fayl o'zi hech qayerda saqlanmaydi
    topic TEXT,
    found INTEGER,                               -- 1 topildi | 0 topilmadi | NULL AI ishlamagan
    sources TEXT,
    feedback INTEGER NOT NULL DEFAULT 0,         -- 1 yoqdi | -1 yoqmadi
    tokens_in INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    tg_message_id INTEGER,
    author TEXT,                                 -- admin xabarida: qaysi admin yuborgan
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id, id);
CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at);
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,                          -- daily | weekly | monthly
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    stats_json TEXT NOT NULL,
    content_md TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS video_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    topic TEXT,
    role TEXT,
    question_count INTEGER NOT NULL DEFAULT 0,
    content_md TEXT NOT NULL,
    period_start TEXT,
    period_end TEXT,
    created_at TEXT NOT NULL
);
"""


class Database(FeaturesMixin, OpsMixin):
    def __init__(self, path: Path | str):
        self.path = str(path)
        self.conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA foreign_keys=ON")
        if self.path != ":memory:":
            await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.executescript(SCHEMA)
        await self.conn.executescript(FEATURE_SCHEMA)
        await self.conn.executescript(OPS_SCHEMA)
        ucols = [r[1] for r in await (await self.conn.execute("PRAGMA table_info(users)")).fetchall()]
        if "assigned_to" not in ucols:
            await self.conn.execute("ALTER TABLE users ADD COLUMN assigned_to INTEGER")
            await self.conn.execute("ALTER TABLE users ADD COLUMN assigned_at TEXT")
        cols = [r[1] for r in await (await self.conn.execute("PRAGMA table_info(messages)")).fetchall()]
        if "author" not in cols:  # eski bazani yangilash
            await self.conn.execute("ALTER TABLE messages ADD COLUMN author TEXT")
        await self.conn.commit()
        await self.seed_defaults()
        await self.seed_holidays()

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()
            self.conn = None

    # ---------- past darajadagi yordamchilar ----------
    async def _all(self, sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
        assert self.conn
        async with self.conn.execute(sql, params) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def _one(self, sql: str, params: tuple | list = ()) -> dict[str, Any] | None:
        rows = await self._all(sql, params)
        return rows[0] if rows else None

    async def _exec(self, sql: str, params: tuple | list = ()) -> int:
        assert self.conn
        cur = await self.conn.execute(sql, params)
        await self.conn.commit()
        return cur.lastrowid or 0

    # ---------- foydalanuvchilar ----------
    async def get_user(self, user_id: int) -> dict | None:
        return await self._one("SELECT * FROM users WHERE id=?", (user_id,))

    async def get_user_by_tg(self, tg_id: int) -> dict | None:
        return await self._one("SELECT * FROM users WHERE tg_id=?", (tg_id,))

    async def create_user(self, tg_id: int, tg_username: str | None, full_name: str, phone: str | None,
                          tech_name: str | None, role: str | None, status: str = "pending") -> int:
        now = ts()
        approved = now if status == "approved" else None
        try:
            return await self._exec(
                "INSERT INTO users (tg_id, tg_username, full_name, phone, tech_name, role, status, created_at, approved_at, last_message_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (tg_id, tg_username, full_name, phone, tech_name, role, status, now, approved, now),
            )
        except aiosqlite.IntegrityError:
            # Telegram bir xil /start yangilanishini bir necha marta (masalan bot qayta ishga
            # tushganda pending update'lar qayta yuborilganda) deyarli bir vaqtda yuborishi mumkin —
            # shu tg_id uchun boshqa so'rov allaqachon yozuvni yaratgan bo'lsa, xato bermay o'shani qaytaramiz.
            existing = await self.get_user_by_tg(tg_id)
            if existing:
                return existing["id"]
            raise

    async def update_registration(self, user_id: int, tg_username: str | None, full_name: str, phone: str | None,
                                  tech_name: str | None, role: str | None) -> None:
        await self._exec(
            "UPDATE users SET tg_username=?, full_name=?, phone=?, tech_name=?, role=?, status='pending' WHERE id=?",
            (tg_username, full_name, phone, tech_name, role, user_id),
        )

    async def set_status(self, user_id: int, status: str) -> None:
        if status == "approved":
            await self._exec("UPDATE users SET status=?, approved_at=? WHERE id=?", (status, ts(), user_id))
        else:
            await self._exec("UPDATE users SET status=? WHERE id=?", (status, user_id))

    async def set_mode(self, user_id: int, mode: str) -> None:
        await self._exec("UPDATE users SET mode=?, mode_since=? WHERE id=?", (mode, ts(), user_id))

    async def set_attention(self, user_id: int, value: bool) -> None:
        await self._exec("UPDATE users SET needs_attention=? WHERE id=?", (1 if value else 0, user_id))

    async def mark_read(self, user_id: int) -> None:
        await self._exec("UPDATE users SET unread=0 WHERE id=?", (user_id,))

    async def touch_photo_notified(self, user_id: int) -> None:
        await self._exec("UPDATE users SET photo_notified_at=? WHERE id=?", (ts(), user_id))

    async def list_users(self, status: str | None = None, q: str | None = None) -> list[dict]:
        sql, params = "SELECT * FROM users WHERE 1=1", []
        if status:
            sql += " AND status=?"
            params.append(status)
        if q:
            like = f"%{q.strip()}%"
            sql += " AND (full_name LIKE ? OR phone LIKE ? OR tech_name LIKE ? OR tg_username LIKE ? OR CAST(tg_id AS TEXT) LIKE ?)"
            params += [like] * 5
        sql += " ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END, created_at DESC"
        return await self._all(sql, params)

    async def count_users_by_status(self) -> dict[str, int]:
        rows = await self._all("SELECT status, COUNT(*) c FROM users GROUP BY status")
        return {r["status"]: r["c"] for r in rows}

    # ---------- xabarlar ----------
    async def add_message(self, user_id: int, sender: str, kind: str = "text", text: str | None = None,
                          file_id: str | None = None, topic: str | None = None, found: bool | None = None,
                          sources: list[str] | None = None, tokens_in: int = 0, tokens_out: int = 0,
                          tg_message_id: int | None = None, author: str | None = None) -> int:
        now = ts()
        msg_id = await self._exec(
            "INSERT INTO messages (user_id, sender, kind, text, file_id, topic, found, sources, tokens_in, tokens_out,"
            " tg_message_id, author, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (user_id, sender, kind, text, file_id, topic, None if found is None else int(found),
             json.dumps(sources, ensure_ascii=False) if sources else None, tokens_in, tokens_out, tg_message_id, author, now),
        )
        if sender == "user":
            await self._exec("UPDATE users SET last_message_at=?, unread=unread+1 WHERE id=?", (now, user_id))
        else:
            await self._exec("UPDATE users SET last_message_at=? WHERE id=?", (now, user_id))
        return msg_id

    async def update_message_analysis(self, msg_id: int, topic: str | None, found: bool | None) -> None:
        await self._exec("UPDATE messages SET topic=?, found=? WHERE id=?",
                         (topic, None if found is None else int(found), msg_id))

    async def get_message(self, msg_id: int) -> dict | None:
        return await self._one("SELECT * FROM messages WHERE id=?", (msg_id,))

    async def set_feedback(self, msg_id: int, value: int) -> None:
        await self._exec("UPDATE messages SET feedback=? WHERE id=?", (value, msg_id))

    async def list_messages(self, user_id: int, after_id: int = 0, limit: int = 300) -> list[dict]:
        rows = await self._all(
            "SELECT * FROM (SELECT * FROM messages WHERE user_id=? AND id>? ORDER BY id DESC LIMIT ?) ORDER BY id ASC",
            (user_id, after_id, limit),
        )
        return rows

    async def ai_history(self, user_id: int, turns: int) -> list[dict]:
        """AI ga yuboriladigan oxirgi matnli xabarlar (rasm va admin xabarlari kirmaydi)."""
        rows = await self._all(
            "SELECT sender, text FROM messages WHERE user_id=? AND kind='text' AND sender IN ('user','bot')"
            " AND text IS NOT NULL ORDER BY id DESC LIMIT ?",
            (user_id, turns * 2),
        )
        return list(reversed(rows))

    async def conversations(self, filter_: str = "all", q: str | None = None, limit: int = 200,
                            admin_id: int | None = None) -> list[dict]:
        sql = (
            "SELECT u.*, (SELECT text FROM messages m WHERE m.user_id=u.id ORDER BY m.id DESC LIMIT 1) AS last_text,"
            " (SELECT kind FROM messages m WHERE m.user_id=u.id ORDER BY m.id DESC LIMIT 1) AS last_kind,"
            " (SELECT sender FROM messages m WHERE m.user_id=u.id ORDER BY m.id DESC LIMIT 1) AS last_sender"
            " FROM users u WHERE EXISTS (SELECT 1 FROM messages m WHERE m.user_id=u.id)"
        )
        params: list[Any] = []
        if filter_ == "attention":
            sql += " AND u.needs_attention=1"
        elif filter_ == "unread":
            sql += " AND u.unread>0"
        elif filter_ == "mine":
            sql += " AND u.assigned_to=?"
            params.append(admin_id or 0)
        elif filter_ == "unassigned":
            sql += " AND u.assigned_to IS NULL"
        if q:
            like = f"%{q.strip()}%"
            sql += " AND (u.full_name LIKE ? OR u.tech_name LIKE ? OR u.phone LIKE ?)"
            params += [like] * 3
        sql += " ORDER BY u.needs_attention DESC, u.last_message_at DESC LIMIT ?"
        params.append(limit)
        return await self._all(sql, params)

    async def dashboard_counts(self, since: str) -> dict[str, int]:
        one = lambda r: (r or {}).get("c", 0)  # noqa: E731
        return {
            "pending": one(await self._one("SELECT COUNT(*) c FROM users WHERE status='pending'")),
            "approved": one(await self._one("SELECT COUNT(*) c FROM users WHERE status='approved'")),
            "attention": one(await self._one("SELECT COUNT(*) c FROM users WHERE needs_attention=1")),
            "unread": one(await self._one("SELECT COUNT(*) c FROM users WHERE unread>0")),
            "faq_pending": one(await self._one("SELECT COUNT(*) c FROM faq_items WHERE status='pending'")),
            "errors_today": one(await self._one("SELECT COUNT(*) c FROM error_log WHERE created_at>=?", (since,))),
            "questions_today": one(await self._one(
                "SELECT COUNT(*) c FROM messages WHERE sender='user' AND kind='text' AND created_at>=?", (since,))),
            "unanswered_today": one(await self._one(
                "SELECT COUNT(*) c FROM messages WHERE sender='user' AND found=0 AND created_at>=?", (since,))),
        }

    # ---------- hisobotlar ----------
    async def add_report(self, kind: str, start: str, end: str, stats: dict, content_md: str) -> int:
        return await self._exec(
            "INSERT INTO reports (kind, period_start, period_end, stats_json, content_md, created_at) VALUES (?,?,?,?,?,?)",
            (kind, start, end, json.dumps(stats, ensure_ascii=False), content_md, ts()),
        )

    async def list_reports(self, limit: int = 100) -> list[dict]:
        return await self._all(
            "SELECT id, kind, period_start, period_end, created_at FROM reports ORDER BY id DESC LIMIT ?", (limit,))

    async def get_report(self, report_id: int) -> dict | None:
        row = await self._one("SELECT * FROM reports WHERE id=?", (report_id,))
        if row:
            row["stats"] = json.loads(row["stats_json"])
        return row

    async def add_video_plan(self, title: str, topic: str, role: str | None, question_count: int, content_md: str,
                             start: str, end: str) -> int:
        return await self._exec(
            "INSERT INTO video_plans (title, topic, role, question_count, content_md, period_start, period_end, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)", (title, topic, role, question_count, content_md, start, end, ts()))

    async def list_video_plans(self, limit: int = 100) -> list[dict]:
        return await self._all(
            "SELECT id, title, topic, role, question_count, period_start, period_end, created_at FROM video_plans"
            " ORDER BY id DESC LIMIT ?", (limit,))

    async def get_video_plan(self, plan_id: int) -> dict | None:
        return await self._one("SELECT * FROM video_plans WHERE id=?", (plan_id,))

    # ---------- hisobot statistikasi ----------
    async def period_stats(self, start: str, end: str, tz_offset_min: int = 0) -> dict[str, Any]:
        """[start, end) oralig'i uchun statistika (UTC satrlari)."""
        p = (start, end)
        one = lambda r, k="c": (r or {}).get(k) or 0  # noqa: E731
        q_where = "sender='user' AND kind='text' AND created_at>=? AND created_at<?"
        s: dict[str, Any] = {}
        s["questions"] = one(await self._one(f"SELECT COUNT(*) c FROM messages WHERE {q_where}", p))
        s["answered"] = one(await self._one(f"SELECT COUNT(*) c FROM messages WHERE {q_where} AND found=1", p))
        s["unanswered"] = one(await self._one(f"SELECT COUNT(*) c FROM messages WHERE {q_where} AND found=0", p))
        s["admin_mode_messages"] = one(await self._one(f"SELECT COUNT(*) c FROM messages WHERE {q_where} AND found IS NULL", p))
        s["photos"] = one(await self._one(
            "SELECT COUNT(*) c FROM messages WHERE sender='user' AND kind='photo' AND created_at>=? AND created_at<?", p))
        s["other_media"] = one(await self._one(
            "SELECT COUNT(*) c FROM messages WHERE sender='user' AND kind='other' AND created_at>=? AND created_at<?", p))
        s["admin_messages"] = one(await self._one(
            "SELECT COUNT(*) c FROM messages WHERE sender='admin' AND created_at>=? AND created_at<?", p))
        s["active_users"] = one(await self._one(
            "SELECT COUNT(DISTINCT user_id) c FROM messages WHERE sender='user' AND created_at>=? AND created_at<?", p))
        s["new_requests"] = one(await self._one("SELECT COUNT(*) c FROM users WHERE created_at>=? AND created_at<?", p))
        s["approved_users"] = one(await self._one("SELECT COUNT(*) c FROM users WHERE approved_at>=? AND approved_at<?", p))
        s["fb_up"] = one(await self._one(
            "SELECT COUNT(*) c FROM messages WHERE sender='bot' AND feedback=1 AND created_at>=? AND created_at<?", p))
        s["fb_down"] = one(await self._one(
            "SELECT COUNT(*) c FROM messages WHERE sender='bot' AND feedback=-1 AND created_at>=? AND created_at<?", p))
        tok = await self._one(
            "SELECT COALESCE(SUM(tokens_in),0) a, COALESCE(SUM(tokens_out),0) b FROM messages"
            " WHERE sender='bot' AND created_at>=? AND created_at<?", p)
        s["tokens_in"], s["tokens_out"] = one(tok, "a"), one(tok, "b")
        s["by_topic"] = await self._all(
            f"SELECT COALESCE(topic,'Boshqa') topic, COUNT(*) n, SUM(CASE WHEN found=0 THEN 1 ELSE 0 END) unanswered"
            f" FROM messages WHERE {q_where} GROUP BY COALESCE(topic,'Boshqa') ORDER BY n DESC", p)
        s["by_role"] = await self._all(
            "SELECT COALESCE(u.role,'Noma''lum') role, COUNT(*) n FROM messages m JOIN users u ON u.id=m.user_id"
            " WHERE m.sender='user' AND m.kind='text' AND m.created_at>=? AND m.created_at<? GROUP BY COALESCE(u.role,'Noma''lum')"
            " ORDER BY n DESC", p)
        s["by_tech"] = await self._all(
            "SELECT COALESCE(u.tech_name,'Noma''lum') tech, COUNT(*) n FROM messages m JOIN users u ON u.id=m.user_id"
            " WHERE m.sender='user' AND m.kind='text' AND m.created_at>=? AND m.created_at<? GROUP BY COALESCE(u.tech_name,'Noma''lum')"
            " ORDER BY n DESC LIMIT 10", p)
        s["by_hour"] = await self._all(
            "SELECT CAST(strftime('%H', created_at, ?) AS INTEGER) h, COUNT(*) n FROM messages WHERE " + q_where +
            " GROUP BY h ORDER BY h", (f"{tz_offset_min:+d} minutes", start, end))
        return s

    async def period_questions(self, start: str, end: str, topic: str | None = None, only_unanswered: bool = False,
                               limit: int = 200) -> list[dict]:
        sql = ("SELECT m.id, m.text, m.topic, m.found, u.role, m.created_at, "
               "(SELECT b.text FROM messages b WHERE b.user_id=m.user_id AND b.sender='bot' AND b.id>m.id ORDER BY b.id LIMIT 1) AS bot_answer,"
               "(SELECT b.feedback FROM messages b WHERE b.user_id=m.user_id AND b.sender='bot' AND b.id>m.id ORDER BY b.id LIMIT 1) AS feedback "
               "FROM messages m JOIN users u ON u.id=m.user_id "
               "WHERE m.sender='user' AND m.kind='text' AND m.created_at>=? AND m.created_at<?")
        params: list[Any] = [start, end]
        if topic:
            sql += " AND COALESCE(m.topic,'Boshqa')=?"
            params.append(topic)
        if only_unanswered:
            sql += " AND m.found=0"
        sql += " ORDER BY m.id DESC LIMIT ?"
        params.append(limit)
        return await self._all(sql, params)
