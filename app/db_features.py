"""Qo'shimcha imkoniyatlar uchun jadvallar va so'rovlar: bilimlar bazasi, FAQ, video kutubxona, shablonlar, viktorina."""
from __future__ import annotations

import hashlib
import json
import random
import re
from datetime import datetime, timezone
from typing import Any


def ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

FEATURE_SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS kb_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    topic TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    source_msg_id INTEGER,
    created_by TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS faq_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    topic TEXT,
    status TEXT NOT NULL DEFAULT 'pending',      -- pending | approved | hidden
    ask_count INTEGER NOT NULL DEFAULT 0,
    views INTEGER NOT NULL DEFAULT 0,
    kb_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lib_videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    topic TEXT,
    description TEXT,
    keywords TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    views INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reply_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS quiz_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,
    topic TEXT,
    question TEXT NOT NULL,
    options TEXT NOT NULL,                       -- JSON: 3 ta variant
    correct INTEGER NOT NULL,                    -- 0..2
    explanation TEXT,
    source TEXT,
    qhash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(role, qhash)
);
CREATE TABLE IF NOT EXISTS quiz_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    day TEXT NOT NULL,
    question_ids TEXT NOT NULL,                  -- JSON ro'yxat (tartib bilan)
    current INTEGER NOT NULL DEFAULT 0,
    score INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'sent',         -- sent | done
    sent_at TEXT NOT NULL,
    finished_at TEXT,
    UNIQUE(user_id, day)
);
CREATE TABLE IF NOT EXISTS quiz_assigned (
    user_id INTEGER NOT NULL,
    question_id INTEGER NOT NULL,
    session_id INTEGER NOT NULL,
    PRIMARY KEY (user_id, question_id)
);
CREATE TABLE IF NOT EXISTS quiz_answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    question_id INTEGER NOT NULL,
    chosen INTEGER NOT NULL,
    is_correct INTEGER NOT NULL,
    answered_at TEXT NOT NULL,
    UNIQUE(session_id, question_id)
);
CREATE TABLE IF NOT EXISTS announcements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL DEFAULT 'info',           -- info | important | reminder
    title TEXT,
    text TEXT,
    image_file_id TEXT,                          -- faqat Telegram file_id (rasm diskka yozilmaydi)
    audience TEXT NOT NULL,                      -- JSON: {"mode": all|roles|users, "roles": [...], "users": [...]}
    ack_required INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'draft',        -- draft | scheduled | sending | sent
    scheduled_at TEXT,
    author TEXT,
    created_at TEXT NOT NULL,
    sent_at TEXT
);
CREATE TABLE IF NOT EXISTS announcement_recipients (
    ann_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',      -- pending | sent | failed
    tg_message_id INTEGER,
    error TEXT,
    sent_at TEXT,
    acked_at TEXT,
    PRIMARY KEY (ann_id, user_id)
);
"""

DEFAULT_TEMPLATES = [
    ("Salomlashish", "Assalomu alaykum, {ism}! Savolingiz bo'yicha yordam beraman."),
    ("Aniqlashtirish", "{ism}, savolingizni aniqroq yozib bera olasizmi? Qaysi bo'lim va qaysi amal haqida so'rayapsiz? "
                       "Imkon bo'lsa, ekrandan skrinshot yuboring (shaxsiy ma'lumotlarni yopib)."),
    ("Ko'rib chiqilmoqda", "Savolingiz ko'rib chiqilmoqda, tez orada javob beraman. Sabringiz uchun rahmat."),
    ("Muammo hal bo'ldi", "Muammo hal bo'lganini tekshirib ko'ring. Yana savol tug'ilsa, bemalol yozing."),
    ("Yopilish", "Yana savollaringiz bo'lsa, yozing. Omad tilayman!"),
]

_TOKEN = re.compile(r"[a-z0-9o'g']+", re.I)


def qhash(question: str) -> str:
    norm = re.sub(r"[^a-z0-9]+", " ", question.lower().replace("‘", "'").replace("’", "'")).strip()
    return hashlib.sha1(norm.encode()).hexdigest()[:16]


class FeaturesMixin:
    # ---------- kv ----------
    async def get_kv(self, key: str, default: str | None = None) -> str | None:
        row = await self._one("SELECT value FROM kv WHERE key=?", (key,))
        return row["value"] if row else default

    async def set_kv(self, key: str, value: str | None) -> None:
        await self._exec("INSERT INTO kv (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                         (key, value))

    async def seed_defaults(self) -> None:
        row = await self._one("SELECT COUNT(*) c FROM reply_templates")
        if row and row["c"] == 0:
            for title, text in DEFAULT_TEMPLATES:
                await self.add_template(title, text)

    # ---------- bilimlar bazasi ----------
    async def add_kb(self, question: str, answer: str, topic: str | None = None, created_by: str | None = None,
                     source_msg_id: int | None = None) -> int:
        now = ts()
        return await self._exec(
            "INSERT INTO kb_entries (question, answer, topic, source_msg_id, created_by, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?)", (question, answer, topic, source_msg_id, created_by, now, now))

    async def update_kb(self, kb_id: int, question: str, answer: str, topic: str | None, active: bool = True) -> None:
        await self._exec("UPDATE kb_entries SET question=?, answer=?, topic=?, active=?, updated_at=? WHERE id=?",
                         (question, answer, topic, 1 if active else 0, ts(), kb_id))

    async def delete_kb(self, kb_id: int) -> None:
        await self._exec("DELETE FROM kb_entries WHERE id=?", (kb_id,))

    async def get_kb(self, kb_id: int) -> dict | None:
        return await self._one("SELECT * FROM kb_entries WHERE id=?", (kb_id,))

    async def list_kb(self, q: str | None = None, active_only: bool = False) -> list[dict]:
        sql, params = "SELECT * FROM kb_entries WHERE 1=1", []
        if active_only:
            sql += " AND active=1"
        if q:
            like = f"%{q.strip()}%"
            sql += " AND (question LIKE ? OR answer LIKE ? OR topic LIKE ?)"
            params += [like] * 3
        return await self._all(sql + " ORDER BY id DESC", params)

    # ---------- FAQ ----------
    async def add_faq(self, question: str, answer: str, topic: str | None, status: str = "pending",
                      ask_count: int = 0, kb_id: int | None = None) -> int:
        now = ts()
        return await self._exec(
            "INSERT INTO faq_items (question, answer, topic, status, ask_count, kb_id, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?)", (question, answer, topic, status, ask_count, kb_id, now, now))

    async def update_faq(self, faq_id: int, question: str, answer: str, topic: str | None) -> None:
        await self._exec("UPDATE faq_items SET question=?, answer=?, topic=?, updated_at=? WHERE id=?",
                         (question, answer, topic, ts(), faq_id))

    async def set_faq_status(self, faq_id: int, status: str) -> None:
        await self._exec("UPDATE faq_items SET status=?, updated_at=? WHERE id=?", (status, ts(), faq_id))

    async def set_faq_count(self, faq_id: int, count: int) -> None:
        await self._exec("UPDATE faq_items SET ask_count=? WHERE id=?", (count, faq_id))

    async def delete_faq(self, faq_id: int) -> None:
        await self._exec("DELETE FROM faq_items WHERE id=?", (faq_id,))

    async def get_faq(self, faq_id: int) -> dict | None:
        return await self._one("SELECT * FROM faq_items WHERE id=?", (faq_id,))

    async def list_faq(self, status: str | None = None) -> list[dict]:
        if status:
            return await self._all("SELECT * FROM faq_items WHERE status=? ORDER BY ask_count DESC, id DESC", (status,))
        return await self._all("SELECT * FROM faq_items ORDER BY ask_count DESC, id DESC")

    async def faq_topics(self) -> list[dict]:
        return await self._all(
            "SELECT COALESCE(topic,'Boshqa') topic, COUNT(*) n FROM faq_items WHERE status='approved'"
            " GROUP BY COALESCE(topic,'Boshqa') ORDER BY n DESC")

    async def faq_by_topic(self, topic: str) -> list[dict]:
        return await self._all(
            "SELECT * FROM faq_items WHERE status='approved' AND COALESCE(topic,'Boshqa')=?"
            " ORDER BY ask_count DESC, id DESC", (topic,))

    async def inc_faq_views(self, faq_id: int) -> None:
        await self._exec("UPDATE faq_items SET views=views+1 WHERE id=?", (faq_id,))

    # ---------- video kutubxona ----------
    async def add_lib_video(self, title: str, url: str, topic: str | None, description: str | None,
                            keywords: str | None) -> int:
        return await self._exec(
            "INSERT INTO lib_videos (title, url, topic, description, keywords, created_at) VALUES (?,?,?,?,?,?)",
            (title, url, topic, description, keywords, ts()))

    async def update_lib_video(self, vid: int, title: str, url: str, topic: str | None, description: str | None,
                               keywords: str | None, active: bool = True) -> None:
        await self._exec(
            "UPDATE lib_videos SET title=?, url=?, topic=?, description=?, keywords=?, active=? WHERE id=?",
            (title, url, topic, description, keywords, 1 if active else 0, vid))

    async def delete_lib_video(self, vid: int) -> None:
        await self._exec("DELETE FROM lib_videos WHERE id=?", (vid,))

    async def get_lib_video(self, vid: int) -> dict | None:
        return await self._one("SELECT * FROM lib_videos WHERE id=?", (vid,))

    async def list_lib_videos(self, active_only: bool = False) -> list[dict]:
        sql = "SELECT * FROM lib_videos" + (" WHERE active=1" if active_only else "")
        return await self._all(sql + " ORDER BY COALESCE(topic,''), id DESC")

    async def inc_video_views(self, vid: int) -> None:
        await self._exec("UPDATE lib_videos SET views=views+1 WHERE id=?", (vid,))

    # ---------- javob shablonlari ----------
    async def add_template(self, title: str, text: str) -> int:
        return await self._exec("INSERT INTO reply_templates (title, text, created_at) VALUES (?,?,?)",
                                (title, text, ts()))

    async def update_template(self, tid: int, title: str, text: str) -> None:
        await self._exec("UPDATE reply_templates SET title=?, text=? WHERE id=?", (title, text, tid))

    async def delete_template(self, tid: int) -> None:
        await self._exec("DELETE FROM reply_templates WHERE id=?", (tid,))

    async def get_template(self, tid: int) -> dict | None:
        return await self._one("SELECT * FROM reply_templates WHERE id=?", (tid,))

    async def list_templates(self) -> list[dict]:
        return await self._all("SELECT * FROM reply_templates ORDER BY id")

    # ---------- foydalanuvchini tahrirlash ----------
    async def update_user_profile(self, user_id: int, full_name: str, phone: str | None, tech_name: str | None,
                                  role: str | None) -> None:
        await self._exec("UPDATE users SET full_name=?, phone=?, tech_name=?, role=? WHERE id=?",
                         (full_name, phone, tech_name, role, user_id))

    # ---------- javob kutayotgan suhbatlar ----------
    async def waiting_chats(self) -> list[dict]:
        return await self._all(
            "SELECT u.id, u.full_name, u.role, u.tech_name, u.last_message_at,"
            " (SELECT text FROM messages m WHERE m.user_id=u.id AND m.sender='user' ORDER BY m.id DESC LIMIT 1) AS last_text,"
            " (SELECT kind FROM messages m WHERE m.user_id=u.id AND m.sender='user' ORDER BY m.id DESC LIMIT 1) AS last_kind"
            " FROM users u WHERE u.needs_attention=1 ORDER BY u.last_message_at")

    # ---------- viktorina ----------
    async def add_quiz_questions(self, role: str, items: list[dict]) -> int:
        """items: {question, options[3], correct(0..2), explanation, topic, source}. Variantlar tasodifiy aralashtiriladi."""
        added = 0
        for it in items:
            opts = [str(o).strip() for o in it.get("options", [])][:3]
            q = str(it.get("question") or "").strip()
            try:
                correct = int(it.get("correct"))
            except (TypeError, ValueError):
                continue
            if len(opts) != 3 or not q or not all(opts) or not 0 <= correct <= 2 or len(set(opts)) != 3:
                continue
            order = [0, 1, 2]
            random.shuffle(order)
            opts2 = [opts[i] for i in order]
            correct2 = order.index(correct)
            try:
                await self._exec(
                    "INSERT INTO quiz_questions (role, topic, question, options, correct, explanation, source, qhash, created_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (role, it.get("topic"), q, json.dumps(opts2, ensure_ascii=False), correct2,
                     (it.get("explanation") or "").strip() or None, it.get("source"), qhash(q), ts()))
                added += 1
            except Exception:  # noqa: BLE001  (takror savol: UNIQUE(role, qhash))
                continue
        return added

    async def get_quiz_question(self, qid: int) -> dict | None:
        row = await self._one("SELECT * FROM quiz_questions WHERE id=?", (qid,))
        if row:
            row["options"] = json.loads(row["options"])
        return row

    async def quiz_pool_size(self, role: str) -> int:
        return (await self._one("SELECT COUNT(*) c FROM quiz_questions WHERE role=?", (role,)) or {}).get("c", 0)

    async def quiz_unseen_count(self, role: str, user_id: int) -> int:
        row = await self._one(
            "SELECT COUNT(*) c FROM quiz_questions q WHERE q.role=? AND NOT EXISTS"
            " (SELECT 1 FROM quiz_assigned a WHERE a.user_id=? AND a.question_id=q.id)", (role, user_id))
        return (row or {}).get("c", 0)

    async def quiz_pick_unseen(self, role: str, user_id: int, n: int) -> list[int]:
        rows = await self._all(
            "SELECT q.id FROM quiz_questions q WHERE q.role=? AND NOT EXISTS"
            " (SELECT 1 FROM quiz_assigned a WHERE a.user_id=? AND a.question_id=q.id) ORDER BY RANDOM() LIMIT ?",
            (role, user_id, n))
        return [r["id"] for r in rows]

    async def quiz_existing_questions(self, role: str, limit: int = 200) -> list[str]:
        rows = await self._all("SELECT question FROM quiz_questions WHERE role=? ORDER BY id DESC LIMIT ?", (role, limit))
        return [r["question"] for r in rows]

    async def get_quiz_session(self, user_id: int, day: str) -> dict | None:
        row = await self._one("SELECT * FROM quiz_sessions WHERE user_id=? AND day=?", (user_id, day))
        if row:
            row["question_ids"] = json.loads(row["question_ids"])
        return row

    async def get_quiz_session_by_id(self, sid: int) -> dict | None:
        row = await self._one("SELECT * FROM quiz_sessions WHERE id=?", (sid,))
        if row:
            row["question_ids"] = json.loads(row["question_ids"])
        return row

    async def create_quiz_session(self, user_id: int, day: str, qids: list[int]) -> int:
        sid = await self._exec("INSERT INTO quiz_sessions (user_id, day, question_ids, sent_at) VALUES (?,?,?,?)",
                               (user_id, day, json.dumps(qids), ts()))
        for q in qids:
            await self._exec("INSERT OR IGNORE INTO quiz_assigned (user_id, question_id, session_id) VALUES (?,?,?)",
                             (user_id, q, sid))
        return sid

    async def record_quiz_answer(self, session_id: int, user_id: int, question_id: int, chosen: int,
                                 correct: bool) -> bool:
        """Javobni yozadi. Shu savolga oldin javob berilgan bo'lsa False qaytaradi."""
        try:
            await self._exec(
                "INSERT INTO quiz_answers (session_id, user_id, question_id, chosen, is_correct, answered_at)"
                " VALUES (?,?,?,?,?,?)", (session_id, user_id, question_id, chosen, 1 if correct else 0, ts()))
        except Exception:  # noqa: BLE001
            return False
        await self._exec("UPDATE quiz_sessions SET current=current+1, score=score+? WHERE id=?",
                         (1 if correct else 0, session_id))
        return True

    async def finish_quiz_session(self, session_id: int) -> None:
        await self._exec("UPDATE quiz_sessions SET status='done', finished_at=? WHERE id=?", (ts(), session_id))

    async def quiz_candidates(self, day: str, roles: list[str]) -> list[dict]:
        """Bugun hali viktorina yuborilmagan tasdiqlangan xodimlar."""
        marks = ",".join("?" for _ in roles)
        return await self._all(
            f"SELECT * FROM users u WHERE u.status='approved' AND u.role IN ({marks}) AND NOT EXISTS"
            " (SELECT 1 FROM quiz_sessions s WHERE s.user_id=u.id AND s.day=?) ORDER BY u.id", (*roles, day))

    async def quiz_overview(self, since_day: str) -> dict[str, Any]:
        one = lambda r, k="c": (r or {}).get(k) or 0  # noqa: E731
        o: dict[str, Any] = {}
        o["sessions"] = one(await self._one("SELECT COUNT(*) c FROM quiz_sessions WHERE day>=?", (since_day,)))
        o["done"] = one(await self._one("SELECT COUNT(*) c FROM quiz_sessions WHERE day>=? AND status='done'", (since_day,)))
        a = await self._one(
            "SELECT COUNT(*) n, COALESCE(SUM(a.is_correct),0) k FROM quiz_answers a JOIN quiz_sessions s ON s.id=a.session_id"
            " WHERE s.day>=?", (since_day,))
        o["answers"], o["correct"] = one(a, "n"), one(a, "k")
        o["by_user"] = await self._all(
            "SELECT u.id, u.full_name, u.role, u.tech_name, COUNT(DISTINCT s.id) sessions,"
            " SUM(CASE WHEN s.status='done' THEN 1 ELSE 0 END) done,"
            " (SELECT COUNT(*) FROM quiz_answers a WHERE a.user_id=u.id AND a.session_id IN"
            "   (SELECT id FROM quiz_sessions WHERE day>=?)) answers,"
            " (SELECT COALESCE(SUM(is_correct),0) FROM quiz_answers a WHERE a.user_id=u.id AND a.session_id IN"
            "   (SELECT id FROM quiz_sessions WHERE day>=?)) correct"
            " FROM quiz_sessions s JOIN users u ON u.id=s.user_id WHERE s.day>=? GROUP BY u.id ORDER BY correct DESC, answers DESC",
            (since_day, since_day, since_day))
        o["by_role"] = await self._all(
            "SELECT u.role, COUNT(*) answers, SUM(a.is_correct) correct FROM quiz_answers a"
            " JOIN users u ON u.id=a.user_id JOIN quiz_sessions s ON s.id=a.session_id WHERE s.day>=? GROUP BY u.role"
            " ORDER BY answers DESC", (since_day,))
        o["by_topic"] = await self._all(
            "SELECT COALESCE(q.topic,'Boshqa') topic, COUNT(*) answers, SUM(a.is_correct) correct FROM quiz_answers a"
            " JOIN quiz_questions q ON q.id=a.question_id JOIN quiz_sessions s ON s.id=a.session_id WHERE s.day>=?"
            " GROUP BY COALESCE(q.topic,'Boshqa') ORDER BY (CAST(SUM(a.is_correct) AS REAL)/COUNT(*)) ASC", (since_day,))
        o["hardest"] = await self._all(
            "SELECT q.id, q.question, q.role, COUNT(*) answers, SUM(a.is_correct) correct FROM quiz_answers a"
            " JOIN quiz_questions q ON q.id=a.question_id JOIN quiz_sessions s ON s.id=a.session_id WHERE s.day>=?"
            " GROUP BY q.id HAVING COUNT(*)>=2 ORDER BY (CAST(SUM(a.is_correct) AS REAL)/COUNT(*)) ASC LIMIT 8", (since_day,))
        o["pool"] = await self._all("SELECT role, COUNT(*) n FROM quiz_questions GROUP BY role ORDER BY role")
        return o

    # ---------- e'lonlar ----------
    async def add_announcement(self, kind: str, title: str | None, text: str | None, image_file_id: str | None,
                               audience: dict, ack_required: bool, author: str | None) -> int:
        return await self._exec(
            "INSERT INTO announcements (kind, title, text, image_file_id, audience, ack_required, author, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (kind, title, text, image_file_id, json.dumps(audience, ensure_ascii=False), int(ack_required), author, ts()))

    async def get_announcement(self, ann_id: int) -> dict | None:
        row = await self._one("SELECT * FROM announcements WHERE id=?", (ann_id,))
        if row:
            row["aud"] = json.loads(row["audience"] or "{}")
        return row

    async def list_announcements(self, limit: int = 100) -> list[dict]:
        rows = await self._all(
            "SELECT a.*, (SELECT COUNT(*) FROM announcement_recipients r WHERE r.ann_id=a.id) AS total,"
            " (SELECT COUNT(*) FROM announcement_recipients r WHERE r.ann_id=a.id AND r.status='sent') AS delivered,"
            " (SELECT COUNT(*) FROM announcement_recipients r WHERE r.ann_id=a.id AND r.status='failed') AS failed,"
            " (SELECT COUNT(*) FROM announcement_recipients r WHERE r.ann_id=a.id AND r.acked_at IS NOT NULL) AS acked"
            " FROM announcements a ORDER BY a.id DESC LIMIT ?", (limit,))
        for r in rows:
            r["aud"] = json.loads(r["audience"] or "{}")
        return rows

    async def claim_announcement(self, ann_id: int, from_status: tuple[str, ...], to_status: str,
                                 scheduled_at: str | None = None) -> bool:
        """Holatni atomik o'zgartiradi (ikki marta yuborilib ketmasligi uchun)."""
        assert self.conn
        marks = ",".join("?" * len(from_status))
        cur = await self.conn.execute(
            f"UPDATE announcements SET status=?, scheduled_at=? WHERE id=? AND status IN ({marks})",
            (to_status, scheduled_at, ann_id, *from_status))
        await self.conn.commit()
        return cur.rowcount > 0

    async def finish_announcement(self, ann_id: int) -> None:
        await self._exec("UPDATE announcements SET status='sent', sent_at=? WHERE id=?", (ts(), ann_id))

    async def delete_announcement(self, ann_id: int) -> None:
        await self._exec("DELETE FROM announcement_recipients WHERE ann_id=?", (ann_id,))
        await self._exec("DELETE FROM announcements WHERE id=?", (ann_id,))

    async def due_announcements(self, now: str) -> list[dict]:
        return await self._all(
            "SELECT * FROM announcements WHERE (status='scheduled' AND scheduled_at<=?) OR status='sending' ORDER BY id",
            (now,))

    async def audience_users(self, aud: dict) -> list[dict]:
        rows = await self._all("SELECT * FROM users WHERE status='approved' ORDER BY full_name")
        mode = aud.get("mode", "all")
        if mode == "roles":
            roles = set(aud.get("roles") or [])
            rows = [r for r in rows if r.get("role") in roles]
        elif mode == "users":
            ids = {int(x) for x in aud.get("users") or []}
            rows = [r for r in rows if r["id"] in ids]
        return rows

    async def add_recipients(self, ann_id: int, user_ids: list[int]) -> None:
        assert self.conn
        await self.conn.executemany("INSERT OR IGNORE INTO announcement_recipients (ann_id, user_id) VALUES (?,?)",
                                    [(ann_id, u) for u in user_ids])
        await self.conn.commit()

    async def pending_recipients(self, ann_id: int) -> list[dict]:
        return await self._all(
            "SELECT r.user_id, u.tg_id FROM announcement_recipients r JOIN users u ON u.id=r.user_id"
            " WHERE r.ann_id=? AND r.status='pending' ORDER BY r.user_id", (ann_id,))

    async def mark_recipient(self, ann_id: int, user_id: int, status: str, tg_message_id: int | None = None,
                             error: str | None = None) -> None:
        await self._exec("UPDATE announcement_recipients SET status=?, tg_message_id=?, error=?, sent_at=?"
                         " WHERE ann_id=? AND user_id=?", (status, tg_message_id, error, ts(), ann_id, user_id))

    async def ack_announcement(self, ann_id: int, user_id: int) -> bool:
        assert self.conn
        cur = await self.conn.execute(
            "UPDATE announcement_recipients SET acked_at=? WHERE ann_id=? AND user_id=? AND acked_at IS NULL",
            (ts(), ann_id, user_id))
        await self.conn.commit()
        return cur.rowcount > 0

    async def announcement_stats(self, ann_id: int) -> dict:
        row = await self._one(
            "SELECT COUNT(*) total, SUM(status='sent') sent, SUM(status='failed') failed, SUM(status='pending') pending,"
            " SUM(acked_at IS NOT NULL) acked FROM announcement_recipients WHERE ann_id=?", (ann_id,))
        return {k: int(v or 0) for k, v in (row or {}).items()}

    async def announcement_recipients(self, ann_id: int) -> list[dict]:
        return await self._all(
            "SELECT r.*, u.full_name, u.role, u.tg_username FROM announcement_recipients r"
            " JOIN users u ON u.id=r.user_id WHERE r.ann_id=? ORDER BY r.status DESC, u.full_name", (ann_id,))
