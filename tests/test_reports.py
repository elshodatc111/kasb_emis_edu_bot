from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app import reports
from app.db import FMT, ts, utcnow
from tests.conftest import EMP


def test_period_for_daily_uses_tashkent_midnight():
    now = datetime(2026, 9, 26, 15, 0, tzinfo=timezone.utc)   # Toshkentda 20:00
    start, end, label = reports.period_for("daily", "Asia/Tashkent", now)
    assert start == "2026-09-25 19:00:00"                     # 26-sentabr 00:00 (UTC+5)
    assert end == "2026-09-26 15:00:01" and "2026-09-26" in label


def test_period_for_weekly_and_monthly():
    now = datetime(2026, 9, 26, 15, 0, tzinfo=timezone.utc)
    s, e, _ = reports.period_for("weekly", "Asia/Tashkent", now)
    assert s == "2026-09-19 19:00:00"                         # 20-sentabr 00:00 (7 kun, bugun bilan)
    s, e, label = reports.period_for("monthly", "Asia/Tashkent", now)
    assert s == "2026-08-31 19:00:00" and "joriy oy" in label
    now1 = datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc)   # Toshkentda 1-oktabr 09:00
    s, e, label = reports.period_for("monthly", "Asia/Tashkent", now1, scheduled=True)
    assert s == "2026-08-31 19:00:00" and e == "2026-09-30 19:00:00" and "2026-09" in label


async def _seed(ctx):
    uid = await ctx.db.create_user(EMP, "u", "Ali Valiyev", "+998", "Texnikum 1", "O'qituvchi", "approved")
    uid2 = await ctx.db.create_user(EMP + 1, "u2", "Vali Aliyev", "+998", "Texnikum 2", "O'quv bo'limi", "approved")
    for text, topic, found, user in [("q1", "Elektron jurnal", True, uid), ("q2", "Elektron jurnal", True, uid),
                                     ("q3", "Diplomlar", False, uid2), ("q4", None, None, uid2)]:
        mid = await ctx.db.add_message(user, "user", "text", text=text, topic=topic, found=found)
        if found:
            await ctx.db.add_message(user, "bot", "text", text="javob " + text, topic=topic, found=True,
                                     tokens_in=100, tokens_out=10)
    await ctx.db.add_message(uid, "user", "photo", file_id="F")
    await ctx.db.add_message(uid, "admin", "text", text="admin javobi")
    return uid, uid2


async def test_period_stats(ctx):
    await _seed(ctx)
    start = ts(utcnow() - timedelta(hours=1))
    end = ts(utcnow() + timedelta(hours=1))
    s = await ctx.db.period_stats(start, end)
    assert (s["questions"], s["answered"], s["unanswered"], s["admin_mode_messages"]) == (4, 2, 1, 1)
    assert s["photos"] == 1 and s["admin_messages"] == 1 and s["active_users"] == 2 and s["new_requests"] == 2
    assert (s["tokens_in"], s["tokens_out"]) == (200, 20)
    topics = {t["topic"]: t for t in s["by_topic"]}
    assert topics["Elektron jurnal"]["n"] == 2 and topics["Diplomlar"]["unanswered"] == 1 and topics["Boshqa"]["n"] == 1
    assert {r["role"]: r["n"] for r in s["by_role"]} == {"O'qituvchi": 2, "O'quv bo'limi": 2}
    empty = await ctx.db.period_stats("2000-01-01 00:00:00", "2000-01-02 00:00:00")
    assert empty["questions"] == 0 and empty["by_topic"] == []


async def test_generate_report_and_fallback(ctx):
    await _seed(ctx)
    rid = await reports.generate_report("daily", notify=True)
    rep = await ctx.db.get_report(rid)
    assert rep["stats"]["questions"] == 4 and "Asosiy xulosa" in rep["content_md"]
    assert any("Kunlik hisobot tayyor" in t for t in ctx.session.texts_to(1000))
    # AI ishlamasa: raqamli zaxira hisobot
    from app.agent import AgentError

    async def boom(*a, **k):
        raise AgentError("x")

    ctx.agent.report_summary = boom
    rid2 = await reports.generate_report("weekly")
    assert "AI xulosa yozib bera olmadi" in (await ctx.db.get_report(rid2))["content_md"]


async def test_empty_report_skips_ai(ctx):
    rid = await reports.generate_report("daily")
    assert "bo'lmadi" in (await ctx.db.get_report(rid))["content_md"] and ctx.agent.reports == []


async def test_video_plans_pick_top_topics(ctx):
    await _seed(ctx)
    start, end, _ = reports.period_for("daily", "Asia/Tashkent")
    ids = await reports.generate_video_plans("2000-01-01 00:00:00", ts(utcnow() + timedelta(hours=1)))
    assert len(ids) == 1                                        # faqat >=2 savolli mavzu: Elektron jurnal
    plan = await ctx.db.get_video_plan(ids[0])
    assert plan["topic"] == "Elektron jurnal" and plan["question_count"] == 2 and plan["role"] == "O'qituvchi"
    assert plan["title"] == "Elektron jurnal bo'yicha qo'llanma"
    topic, roles, questions = ctx.agent.videos[0]
    assert {q["text"] for q in questions} == {"q1", "q2"} and questions[0]["bot_answer"].startswith("javob")


async def test_hourly_stats_use_local_time(ctx):
    uid = await ctx.db.create_user(EMP, "u", "Ali", "+998", "T", "O'qituvchi", "approved")
    await ctx.db._exec("INSERT INTO messages (user_id, sender, kind, text, created_at) VALUES (?,?,?,?,?)",
                       (uid, "user", "text", "q", "2026-09-26 15:30:00"))
    s = await ctx.db.period_stats("2026-09-26 00:00:00", "2026-09-27 00:00:00", tz_offset_min=300)
    assert s["by_hour"] == [{"h": 20, "n": 1}]                # 15:30 UTC = 20:30 Toshkent
    s = await ctx.db.period_stats("2026-09-26 00:00:00", "2026-09-27 00:00:00")
    assert s["by_hour"] == [{"h": 15, "n": 1}]
