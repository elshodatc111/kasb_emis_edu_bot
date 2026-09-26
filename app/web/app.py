from __future__ import annotations

import html
import logging
import mimetypes
import re
import secrets
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import markdown as md_lib
from aiogram.exceptions import TelegramAPIError
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .. import announce as announce_mod
from .. import faq as faq_mod
from .. import kb as kb_mod
from .. import quiz as quiz_mod
from .. import reports, services
from ..agent import AgentError
from ..constants import ROLE_STATUS_UZ, ROLES, TOPICS
from ..context import get_ctx
from ..db import FMT, parse_ts, utcnow
from ..privacy import mask_sensitive
from .icons import icon, initials

log = logging.getLogger(__name__)
BASE = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE / "templates"))

MAX_IMAGE = 10 * 1024 * 1024
MAX_VIDEO = 50 * 1024 * 1024
CODE_TTL = 300


class NeedLogin(Exception):
    pass


# ------------------------------------------------------------------ Jinja filtrlari
def _local(value: str | None, fmt: str = "%d.%m %H:%M") -> str:
    dt = parse_ts(value)
    if not dt:
        return ""
    tz = ZoneInfo(get_ctx().settings.timezone)
    return dt.replace(tzinfo=timezone.utc).astimezone(tz).strftime(fmt)


def _md(value: str | None) -> str:
    return md_lib.markdown(html.escape(value or ""), extensions=["tables", "sane_lists", "nl2br"])


def _has_sensitive(value: str | None) -> bool:
    return mask_sensitive(value)[1] > 0


def _aud_label(aud: dict) -> str:
    mode = aud.get("mode", "all")
    if mode == "roles":
        return "Rollar: " + ", ".join(aud.get("roles") or [])
    if mode == "users":
        return f"Tanlangan xodimlar ({len(aud.get('users') or [])})"
    return "Barcha tasdiqlangan xodimlar"


templates.env.filters["aud_label"] = _aud_label
templates.env.filters["local"] = _local
templates.env.filters["md"] = _md
templates.env.filters["has_sensitive"] = _has_sensitive
templates.env.globals["icon"] = icon
templates.env.filters["initials"] = initials
templates.env.filters["status_uz"] = lambda s: ROLE_STATUS_UZ.get(s, s)


# ------------------------------------------------------------------ media keshi (faqat xotirada)
class _MemCache:
    def __init__(self, cap: int = 40 * 1024 * 1024):
        self.cap, self.size = cap, 0
        self.d: OrderedDict[str, tuple[bytes, str]] = OrderedDict()

    def get(self, key: str):
        v = self.d.get(key)
        if v:
            self.d.move_to_end(key)
        return v

    def put(self, key: str, data: bytes, ctype: str):
        if len(data) > self.cap // 2:
            return
        self.d[key] = (data, ctype)
        self.size += len(data)
        while self.size > self.cap and self.d:
            _, (old, _c) = self.d.popitem(last=False)
            self.size -= len(old)


_cache = _MemCache()
_codes: dict[int, dict] = {}


# ------------------------------------------------------------------ yordamchilar
def admin_required(request: Request) -> int:
    admin_id = request.session.get("admin_id")
    if not admin_id or admin_id not in get_ctx().settings.admin_ids:
        raise NeedLogin()
    return int(admin_id)


async def csrf_required(request: Request, admin_id: int = Depends(admin_required)) -> int:
    token = request.headers.get("X-CSRF-Token", "")
    expected = request.session.get("csrf", "")
    if not expected or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="CSRF tekshiruvi o'tmadi. Sahifani yangilang.")
    return admin_id


async def render(request: Request, name: str, status_code: int = 200, **context) -> HTMLResponse:
    c = get_ctx()
    if "csrf" not in request.session:
        request.session["csrf"] = secrets.token_hex(16)
    counts = {}
    if request.session.get("admin_id"):
        counts = await c.db.dashboard_counts(_today_start())
    aid = request.session.get("admin_id")
    context.update(csrf=request.session["csrf"], admin_id=aid, counts=counts,
                   admin_name=c.settings.admin_name(aid) if aid else "",
                   base_url=c.settings.base_url)
    return templates.TemplateResponse(request, name, context, status_code=status_code)


def _today_start() -> str:
    tz = ZoneInfo(get_ctx().settings.timezone)
    now = datetime.now(timezone.utc).astimezone(tz)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).strftime(FMT)


def _hx(url: str) -> Response:
    return Response(status_code=200, headers={"HX-Redirect": url})


# ------------------------------------------------------------------ ilova
def create_app() -> FastAPI:
    c = get_ctx()
    app = FastAPI(title="Texnikum yordamchi paneli", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(SessionMiddleware, secret_key=c.settings.secret_key, max_age=12 * 3600, same_site="lax",
                       https_only=c.settings.cookie_secure, session_cookie="texnikum_session")
    app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")

    @app.exception_handler(NeedLogin)
    async def _need_login(request: Request, exc: NeedLogin):
        if request.headers.get("HX-Request"):
            return _hx("/login")
        return RedirectResponse("/login", status_code=303)

    @app.get("/health")
    async def health():
        return PlainTextResponse("ok")

    # ---------------- kirish (Telegram ID + bot orqali bir martalik kod) ----------------
    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        if request.session.get("admin_id"):
            return RedirectResponse("/", status_code=303)
        return await render(request, "login.html", step=1, error=None, tg_id="")

    @app.post("/login/request", response_class=HTMLResponse)
    async def login_request(request: Request, tg_id: str = Form("")):
        ctx = get_ctx()
        tg_id = tg_id.strip()
        if not tg_id.isdigit():
            return await render(request, "login.html", step=1, error="Telegram ID faqat raqamlardan iborat bo'lishi kerak.", tg_id=tg_id)
        uid = int(tg_id)
        if uid in ctx.settings.admin_ids:
            entry = _codes.get(uid)
            if entry and time.time() - entry["sent"] < 30:
                return await render(request, "login.html", step=2, error="Kod yaqinda yuborilgan. 30 soniyadan keyin qayta urining.", tg_id=tg_id)
            code = f"{secrets.randbelow(1_000_000):06d}"
            _codes[uid] = {"code": code, "exp": time.time() + CODE_TTL, "sent": time.time(), "tries": 0}
            try:
                await ctx.bot.send_message(uid, f"Veb-panelga kirish kodi: {code}\nKod 5 daqiqa amal qiladi. "
                                                f"Agar siz so'ramagan bo'lsangiz, hech kimga bermang.")
            except TelegramAPIError as exc:
                log.warning("Kod yuborilmadi: %s", exc)
                return await render(request, "login.html", step=1, tg_id=tg_id,
                                    error="Kodni yuborib bo'lmadi. Avval Telegramda botga /start yuboring.")
        # ID admin bo'lmasa ham bir xil javob ko'rsatiladi (ID larni aniqlab bo'lmasligi uchun)
        return await render(request, "login.html", step=2, error=None, tg_id=tg_id)

    @app.post("/login/verify", response_class=HTMLResponse)
    async def login_verify(request: Request, tg_id: str = Form(""), code: str = Form("")):
        uid = int(tg_id) if tg_id.strip().isdigit() else 0
        entry = _codes.get(uid)
        ok = False
        if entry and time.time() < entry["exp"] and entry["tries"] < 5:
            entry["tries"] += 1
            ok = secrets.compare_digest(entry["code"], code.strip())
        if not ok:
            return await render(request, "login.html", step=2, tg_id=tg_id, status_code=401,
                                error="Kod noto'g'ri yoki muddati tugagan.")
        _codes.pop(uid, None)
        request.session.clear()
        request.session["admin_id"] = uid
        request.session["csrf"] = secrets.token_hex(16)
        return RedirectResponse("/", status_code=303)

    @app.get("/logout")
    async def logout(request: Request):
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    # ---------------- bosh sahifa ----------------
    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request, _: int = Depends(admin_required)):
        ctx = get_ctx()
        attention = await ctx.db.conversations("attention", limit=8)
        pending = (await ctx.db.list_users("pending"))[:8]
        reps = await ctx.db.list_reports(3)
        quiz_today = await ctx.db.quiz_overview(quiz_mod.today())
        return await render(request, "dashboard.html", attention=attention, pending=pending, reports=reps,
                            quiz=quiz_today, page="dashboard")

    @app.get("/counts", response_class=HTMLResponse)
    async def counts(request: Request, page: str = "", _: int = Depends(admin_required)):
        return await render(request, "_counts.html", page=page)

    # ---------------- foydalanuvchilar ----------------
    @app.get("/users", response_class=HTMLResponse)
    async def users_page(request: Request, status: str = "", q: str = "", _: int = Depends(admin_required)):
        rows = await get_ctx().db.list_users(status or None, q or None)
        return await render(request, "users.html", users=rows, status=status, q=q,
                            notice=request.query_params.get("notice"),
                            page="requests" if status == "pending" else "users")

    @app.post("/users/{user_id}/status", response_class=HTMLResponse)
    async def user_status(request: Request, user_id: int, status: str = Form(...), _: int = Depends(csrf_required)):
        if status not in ("approved", "rejected", "blocked"):
            raise HTTPException(400, "Noto'g'ri holat")
        user = await services.decide_user(user_id, status)
        if not user:
            raise HTTPException(404, "Foydalanuvchi topilmadi")
        return await render(request, "_user_row.html", u=user)

    # ---------------- suhbatlar ----------------
    @app.get("/chats", response_class=HTMLResponse)
    async def chats_page(request: Request, filter: str = "all", q: str = "", _: int = Depends(admin_required)):
        convs = await get_ctx().db.conversations(filter, q or None)
        return await render(request, "chats.html", convs=convs, filter=filter, q=q, active=None, user=None,
                            messages=[], page="chats")

    @app.get("/chats/list", response_class=HTMLResponse)
    async def chats_list(request: Request, filter: str = "all", q: str = "", active: int = 0,
                         _: int = Depends(admin_required)):
        convs = await get_ctx().db.conversations(filter, q or None)
        return await render(request, "_conv_list.html", convs=convs, filter=filter, q=q, active=active)

    @app.get("/chats/{user_id}", response_class=HTMLResponse)
    async def chat_page(request: Request, user_id: int, filter: str = "all", q: str = "",
                        _: int = Depends(admin_required)):
        ctx = get_ctx()
        user = await ctx.db.get_user(user_id)
        if not user:
            raise HTTPException(404, "Foydalanuvchi topilmadi")
        await ctx.db.mark_read(user_id)
        convs = await ctx.db.conversations(filter, q or None)
        messages = await ctx.db.list_messages(user_id)
        return await render(request, "chats.html", convs=convs, filter=filter, q=q, active=user_id, user=user,
                            messages=messages, tpls=await ctx.db.list_templates(), page="chats")

    @app.get("/chats/{user_id}/messages", response_class=HTMLResponse)
    async def chat_messages(request: Request, user_id: int, after: int = 0, _: int = Depends(admin_required)):
        ctx = get_ctx()
        messages = await ctx.db.list_messages(user_id, after_id=after)
        if messages:
            await ctx.db.mark_read(user_id)
        return await render(request, "_messages.html", messages=messages)

    @app.post("/chats/{user_id}/send", response_class=HTMLResponse)
    async def chat_send(request: Request, user_id: int, text: str = Form(""), file: UploadFile | None = File(None),
                        admin_id: int = Depends(csrf_required)):
        data, name, ctype = None, "file", ""
        if file is not None and file.filename:
            data = await file.read()
            name, ctype = file.filename, (file.content_type or mimetypes.guess_type(file.filename)[0] or "")
            limit = MAX_IMAGE if ctype.startswith("image/") else MAX_VIDEO
            if not (ctype.startswith("image/") or ctype.startswith("video/")):
                return HTMLResponse('<span class="err">Faqat rasm (skrinshot) yoki video yuborish mumkin.</span>')
            if len(data) > limit:
                return HTMLResponse(f'<span class="err">Fayl juda katta (chegara: {limit // 1024 // 1024} MB).</span>')
        if not data and not text.strip():
            return HTMLResponse('<span class="err">Xabar bo\'sh.</span>')
        try:
            await services.admin_send(user_id, text, admin_id, data, name, ctype)
        except (TelegramAPIError, ValueError) as exc:
            log.warning("Admin xabari yuborilmadi: %s", exc)
            return HTMLResponse(f'<span class="err">Yuborilmadi: {html.escape(str(exc))}</span>')
        return Response(status_code=200, headers={"HX-Trigger": "refresh-msgs,list-refresh"})

    @app.post("/chats/{user_id}/mode", response_class=HTMLResponse)
    async def chat_mode(request: Request, user_id: int, mode: str = Form(...), _: int = Depends(csrf_required)):
        ctx = get_ctx()
        if mode not in ("bot", "admin"):
            raise HTTPException(400, "Noto'g'ri rejim")
        await ctx.db.set_mode(user_id, mode)
        if mode == "bot":
            await ctx.db.set_attention(user_id, False)
        user = await ctx.db.get_user(user_id)
        resp = await render(request, "_chat_head.html", user=user)
        resp.headers["HX-Trigger"] = "list-refresh"
        return resp

    @app.post("/chats/{user_id}/attention", response_class=HTMLResponse)
    async def chat_attention(request: Request, user_id: int, _: int = Depends(csrf_required)):
        ctx = get_ctx()
        await ctx.db.set_attention(user_id, False)
        user = await ctx.db.get_user(user_id)
        resp = await render(request, "_chat_head.html", user=user)
        resp.headers["HX-Trigger"] = "list-refresh"
        return resp

    @app.post("/chats/{user_id}/suggest", response_class=HTMLResponse)
    async def chat_suggest(request: Request, user_id: int, _: int = Depends(csrf_required)):
        ctx = get_ctx()
        msgs = await ctx.db.list_messages(user_id, limit=30)
        for m in msgs:
            if m.get("text"):
                m["text"] = mask_sensitive(m["text"])[0]
        try:
            text = await ctx.agent.suggest_reply(msgs)
        except AgentError as exc:
            text = ""
            return HTMLResponse(
                f'<textarea id="msg-text" name="text" rows="3" placeholder="AI taklif bera olmadi: '
                f'{html.escape(str(exc))[:120]}"></textarea>')
        return HTMLResponse(f'<textarea id="msg-text" name="text" rows="4">{html.escape(text)}</textarea>')

    # ---------------- media (rasm / video) — Telegram'dan olinib, diskka yozilmaydi ----------------
    @app.get("/media/{msg_id}")
    async def media(msg_id: int, _: int = Depends(admin_required)):
        ctx = get_ctx()
        msg = await ctx.db.get_message(msg_id)
        if not msg or not msg.get("file_id") or msg["kind"] not in ("photo", "video"):
            raise HTTPException(404, "Fayl topilmadi")
        headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
        cached = _cache.get(msg["file_id"])
        if cached:
            return Response(cached[0], media_type=cached[1], headers=headers)
        try:
            f = await ctx.bot.get_file(msg["file_id"])
            buf = await ctx.bot.download_file(f.file_path)
            data = buf.read() if hasattr(buf, "read") else bytes(buf)
        except TelegramAPIError as exc:
            log.warning("Media olinmadi: %s", exc)
            raise HTTPException(404, "Faylni Telegramdan olib bo'lmadi (20 MB dan katta yoki eskirgan)")
        ctype = mimetypes.guess_type(f.file_path or "")[0] or ("image/jpeg" if msg["kind"] == "photo" else "video/mp4")
        _cache.put(msg["file_id"], data, ctype)
        return Response(data, media_type=ctype, headers=headers)

    # ---------------- hisobotlar ----------------
    @app.get("/reports", response_class=HTMLResponse)
    async def reports_page(request: Request, _: int = Depends(admin_required)):
        return await render(request, "reports.html", reports=await get_ctx().db.list_reports(), page="reports",
                            kind_uz=reports.KIND_UZ)

    @app.post("/reports/generate", response_class=HTMLResponse)
    async def reports_generate(request: Request, kind: str = Form(...), _: int = Depends(csrf_required)):
        if kind not in reports.KIND_UZ:
            raise HTTPException(400, "Noto'g'ri hisobot turi")
        rid = await reports.generate_report(kind)
        return _hx(f"/reports/{rid}")

    @app.get("/reports/{report_id}", response_class=HTMLResponse)
    async def report_page(request: Request, report_id: int, _: int = Depends(admin_required)):
        rep = await get_ctx().db.get_report(report_id)
        if not rep:
            raise HTTPException(404, "Hisobot topilmadi")
        return await render(request, "report.html", r=rep, page="reports", kind_uz=reports.KIND_UZ)

    # ---------------- video rejalar ----------------
    @app.get("/videos", response_class=HTMLResponse)
    async def videos_page(request: Request, _: int = Depends(admin_required)):
        return await render(request, "videos.html", plans=await get_ctx().db.list_video_plans(), page="videos",
                            notice=request.query_params.get("notice"))

    @app.post("/videos/generate", response_class=HTMLResponse)
    async def videos_generate(request: Request, kind: str = Form("weekly"), _: int = Depends(csrf_required)):
        ctx = get_ctx()
        if kind not in reports.KIND_UZ:
            raise HTTPException(400, "Noto'g'ri davr")
        start, end, _label = reports.period_for(kind, ctx.settings.timezone)
        ids = await reports.generate_video_plans(start, end)
        notice = f"{len(ids)} ta video reja yaratildi." if ids else \
            "Bu davrda yetarli savol (kamida 2 ta bir mavzuda) yoki AI javobi topilmadi."
        return _hx(f"/videos?notice={quote(notice)}")

    @app.get("/videos/{plan_id}", response_class=HTMLResponse)
    async def video_page(request: Request, plan_id: int, _: int = Depends(admin_required)):
        plan = await get_ctx().db.get_video_plan(plan_id)
        if not plan:
            raise HTTPException(404, "Reja topilmadi")
        return await render(request, "video.html", p=plan, page="videos")

    @app.get("/videos/{plan_id}/download")
    async def video_download(plan_id: int, _: int = Depends(admin_required)):
        plan = await get_ctx().db.get_video_plan(plan_id)
        if not plan:
            raise HTTPException(404, "Reja topilmadi")
        fname = f"video_reja_{plan_id}.md"
        return Response(plan["content_md"], media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": f"attachment; filename={fname}"})

    # ---------------- foydalanuvchi ma'lumotlarini tahrirlash ----------------
    @app.get("/users/{user_id}/edit", response_class=HTMLResponse)
    async def user_edit_page(request: Request, user_id: int, _: int = Depends(admin_required)):
        user = await get_ctx().db.get_user(user_id)
        if not user:
            raise HTTPException(404, "Foydalanuvchi topilmadi")
        roles = list(ROLES) + (["Administrator"] if user.get("role") == "Administrator" else [])
        if user.get("role") and user["role"] not in roles:
            roles.append(user["role"])
        return await render(request, "user_edit.html", u=user, roles=roles, page="users")

    @app.post("/users/{user_id}/edit", response_class=HTMLResponse)
    async def user_edit_save(user_id: int, full_name: str = Form(""), phone: str = Form(""), tech_name: str = Form(""),
                             role: str = Form(""), status: str = Form(""), _: int = Depends(csrf_required)):
        ctx = get_ctx()
        user = await ctx.db.get_user(user_id)
        if not user:
            raise HTTPException(404, "Foydalanuvchi topilmadi")
        full_name = " ".join(full_name.split())
        digits = re.sub(r"\D", "", phone)
        if len(full_name) < 3:
            return HTMLResponse('<span class="err">F.I.SH. juda qisqa.</span>')
        if phone.strip() and not 9 <= len(digits) <= 15:
            return HTMLResponse('<span class="err">Telefon raqam noto\'g\'ri.</span>')
        await ctx.db.update_user_profile(user_id, full_name, ("+" + digits) if digits else None,
                                         " ".join(tech_name.split()) or None, role.strip() or None)
        if status in ("pending", "approved", "rejected", "blocked") and status != user["status"]:
            await services.decide_user(user_id, status)
        await services.push({"type": "user", "user_id": user_id})
        return _hx("/users?notice=" + quote("Ma'lumotlar saqlandi."))

    # ---------------- bilimlar bazasi ----------------
    @app.get("/kb", response_class=HTMLResponse)
    async def kb_page(request: Request, q: str = "", edit: int = 0, msg: int = 0, _: int = Depends(admin_required)):
        ctx = get_ctx()
        form = {"id": 0, "question": "", "answer": "", "topic": "", "active": 1}
        if edit:
            row = await ctx.db.get_kb(edit)
            if row:
                form = row
        elif msg:
            m = await ctx.db.get_message(msg)
            if m and m["sender"] == "admin" and m.get("text"):
                prev = await ctx.db._one(
                    "SELECT text FROM messages WHERE user_id=? AND sender='user' AND kind='text' AND id<? ORDER BY id DESC LIMIT 1",
                    (m["user_id"], msg))
                form = {"id": 0, "question": mask_sensitive((prev or {}).get("text") or "")[0], "answer": m["text"],
                        "topic": "", "active": 1, "source_msg_id": msg}
        entries = await ctx.db.list_kb(q or None)
        sync = {"error": await ctx.db.get_kv("kb_sync_error"), "at": await ctx.db.get_kv("kb_synced_at")}
        return await render(request, "kb.html", entries=entries, form=form, q=q, topics=TOPICS, sync=sync,
                            notice=request.query_params.get("notice"), page="kb")

    @app.post("/kb/save", response_class=HTMLResponse)
    async def kb_save(request: Request, kb_id: int = Form(0), question: str = Form(""), answer: str = Form(""),
                      topic: str = Form(""), also_faq: str = Form(""), source_msg_id: int = Form(0),
                      admin_id: int = Depends(csrf_required)):
        ctx = get_ctx()
        question, n1 = kb_mod.clean_entry(question)
        answer, n2 = kb_mod.clean_entry(answer)
        if len(question) < 5 or len(answer) < 5:
            return HTMLResponse('<span class="err">Savol va javob kamida 5 belgidan iborat bo\'lishi kerak.</span>')
        topic = topic if topic in TOPICS else "Boshqa"
        if kb_id:
            old = await ctx.db.get_kb(kb_id)
            if not old:
                raise HTTPException(404, "Yozuv topilmadi")
            await ctx.db.update_kb(kb_id, question, answer, topic, bool(old["active"]))
        else:
            kb_id = await ctx.db.add_kb(question, answer, topic, ctx.settings.admin_name(admin_id), source_msg_id or None)
        if also_faq:
            await ctx.db.add_faq(question, answer, topic, "approved", 0, kb_id)
        note = "Saqlandi. Bot bu javobdan darhol foydalanadi."
        if n1 + n2:
            note += " Shaxsiy ma'lumotlar (PINFL/pasport) yashirildi."
        return _hx("/kb?notice=" + quote(note))

    @app.post("/kb/{kb_id}/toggle", response_class=HTMLResponse)
    async def kb_toggle(kb_id: int, _: int = Depends(csrf_required)):
        ctx = get_ctx()
        row = await ctx.db.get_kb(kb_id)
        if not row:
            raise HTTPException(404, "Yozuv topilmadi")
        await ctx.db.update_kb(kb_id, row["question"], row["answer"], row["topic"], not row["active"])
        return _hx("/kb")

    @app.post("/kb/{kb_id}/delete", response_class=HTMLResponse)
    async def kb_delete(kb_id: int, _: int = Depends(csrf_required)):
        await get_ctx().db.delete_kb(kb_id)
        return _hx("/kb?notice=" + quote("O'chirildi."))

    @app.post("/kb/sync", response_class=HTMLResponse)
    async def kb_sync(_: int = Depends(csrf_required)):
        res = await kb_mod.sync_to_vector_store()
        note = "OpenAI bilimlar bazasi bilan sinxronlandi." if res in ("ok", "skipped") else f"Sinxronlashda xato: {res}"
        return _hx("/kb?notice=" + quote(note))

    # ---------------- FAQ ----------------
    @app.get("/faq", response_class=HTMLResponse)
    async def faq_page(request: Request, status: str = "pending", edit: int = 0, _: int = Depends(admin_required)):
        ctx = get_ctx()
        if status not in ("pending", "approved", "hidden"):
            status = "pending"
        items = await ctx.db.list_faq(status)
        allc = {s_: len(await ctx.db.list_faq(s_)) for s_ in ("pending", "approved", "hidden")}
        return await render(request, "faq.html", items=items, status=status, counts_faq=allc, topics=TOPICS,
                            edit=edit, notice=request.query_params.get("notice"), page="faq")

    @app.post("/faq/save", response_class=HTMLResponse)
    async def faq_save(faq_id: int = Form(0), question: str = Form(""), answer: str = Form(""), topic: str = Form(""),
                       _: int = Depends(csrf_required)):
        ctx = get_ctx()
        question, _n1 = kb_mod.clean_entry(question)
        answer, _n2 = kb_mod.clean_entry(answer)
        if len(question) < 5 or len(answer) < 5:
            return HTMLResponse('<span class="err">Savol va javob kamida 5 belgidan iborat bo\'lishi kerak.</span>')
        topic = topic if topic in TOPICS else "Boshqa"
        if faq_id:
            if not await ctx.db.get_faq(faq_id):
                raise HTTPException(404, "FAQ topilmadi")
            await ctx.db.update_faq(faq_id, question, answer, topic)
            row = await ctx.db.get_faq(faq_id)
            return _hx(f"/faq?status={row['status']}&notice=" + quote("Saqlandi."))
        await ctx.db.add_faq(question, answer, topic, "approved", 0)
        return _hx("/faq?status=approved&notice=" + quote("FAQ qo'shildi va botda ko'rinadi."))

    @app.post("/faq/{faq_id}/status", response_class=HTMLResponse)
    async def faq_status(faq_id: int, status: str = Form(...), _: int = Depends(csrf_required)):
        if status not in ("pending", "approved", "hidden"):
            raise HTTPException(400, "Noto'g'ri holat")
        ctx = get_ctx()
        if not await ctx.db.get_faq(faq_id):
            raise HTTPException(404, "FAQ topilmadi")
        await ctx.db.set_faq_status(faq_id, status)
        await services.push({"type": "faq"})
        return _hx(f"/faq?status={'pending' if status == 'approved' else status}")

    @app.post("/faq/{faq_id}/delete", response_class=HTMLResponse)
    async def faq_delete(faq_id: int, _: int = Depends(csrf_required)):
        await get_ctx().db.delete_faq(faq_id)
        return _hx("/faq")

    @app.post("/faq/analyze", response_class=HTMLResponse)
    async def faq_analyze(_: int = Depends(csrf_required)):
        res = await faq_mod.analyze(notify=False)
        if res["reason"] == "few":
            note = f"Tahlil uchun savollar yetarli emas (kamida {faq_mod.MIN_ITEMS} ta javob berilgan savol kerak)."
        elif res["reason"] == "error":
            note = "AI xato berdi: " + res.get("error", "")
        else:
            note = f"Tahlil tugadi: {res['created']} ta yangi variant, {res['updated']} ta yangilandi."
        return _hx("/faq?status=pending&notice=" + quote(note))

    # ---------------- video kutubxona ----------------
    @app.get("/library", response_class=HTMLResponse)
    async def library_page(request: Request, edit: int = 0, _: int = Depends(admin_required)):
        ctx = get_ctx()
        form = {"id": 0, "title": "", "url": "", "topic": "", "description": "", "keywords": "", "active": 1}
        if edit:
            row = await ctx.db.get_lib_video(edit)
            if row:
                form = row
        return await render(request, "library.html", videos=await ctx.db.list_lib_videos(), form=form, topics=TOPICS,
                            notice=request.query_params.get("notice"), page="library")

    @app.post("/library/save", response_class=HTMLResponse)
    async def library_save(vid: int = Form(0), title: str = Form(""), url: str = Form(""), topic: str = Form(""),
                           description: str = Form(""), keywords: str = Form(""), active: str = Form(""),
                           _: int = Depends(csrf_required)):
        ctx = get_ctx()
        title, url = " ".join(title.split()), url.strip()
        if len(title) < 3:
            return HTMLResponse('<span class="err">Sarlavha kiriting.</span>')
        if not re.match(r"^https?://\S+$", url):
            return HTMLResponse('<span class="err">Havola http:// yoki https:// bilan boshlanishi kerak.</span>')
        topic = topic if topic in TOPICS else "Boshqa"
        desc, kw = description.strip()[:500] or None, keywords.strip()[:200] or None
        if vid:
            if not await ctx.db.get_lib_video(vid):
                raise HTTPException(404, "Video topilmadi")
            await ctx.db.update_lib_video(vid, title, url, topic, desc, kw, bool(active))
        else:
            await ctx.db.add_lib_video(title, url, topic, desc, kw)
        return _hx("/library?notice=" + quote("Saqlandi."))

    @app.post("/library/{vid}/toggle", response_class=HTMLResponse)
    async def library_toggle(vid: int, _: int = Depends(csrf_required)):
        ctx = get_ctx()
        v = await ctx.db.get_lib_video(vid)
        if not v:
            raise HTTPException(404, "Video topilmadi")
        await ctx.db.update_lib_video(vid, v["title"], v["url"], v["topic"], v["description"], v["keywords"], not v["active"])
        return _hx("/library")

    @app.post("/library/{vid}/delete", response_class=HTMLResponse)
    async def library_delete(vid: int, _: int = Depends(csrf_required)):
        await get_ctx().db.delete_lib_video(vid)
        return _hx("/library?notice=" + quote("O'chirildi."))

    # ---------------- javob shablonlari ----------------
    @app.get("/templates", response_class=HTMLResponse)
    async def templates_page(request: Request, edit: int = 0, _: int = Depends(admin_required)):
        ctx = get_ctx()
        form = (await ctx.db.get_template(edit)) if edit else None
        return await render(request, "templates_page.html", tpls=await ctx.db.list_templates(),
                            form=form or {"id": 0, "title": "", "text": ""}, page="templates",
                            notice=request.query_params.get("notice"))

    @app.post("/templates/save", response_class=HTMLResponse)
    async def templates_save(tid: int = Form(0), title: str = Form(""), text: str = Form(""),
                             _: int = Depends(csrf_required)):
        ctx = get_ctx()
        title, text = " ".join(title.split()), text.strip()
        if len(title) < 2 or len(text) < 2:
            return HTMLResponse('<span class="err">Nom va matn kiriting.</span>')
        if tid:
            await ctx.db.update_template(tid, title, text)
        else:
            await ctx.db.add_template(title, text)
        return _hx("/templates?notice=" + quote("Saqlandi."))

    @app.post("/templates/{tid}/delete", response_class=HTMLResponse)
    async def templates_delete(tid: int, _: int = Depends(csrf_required)):
        await get_ctx().db.delete_template(tid)
        return _hx("/templates")

    # ---------------- viktorina ----------------
    @app.get("/quiz", response_class=HTMLResponse)
    async def quiz_page(request: Request, days: int = 7, _: int = Depends(admin_required)):
        ctx = get_ctx()
        days = days if days in (1, 7, 30, 90) else 7
        tz = ZoneInfo(ctx.settings.timezone)
        since = (datetime.now(tz) - timedelta(days=days - 1)).strftime("%Y-%m-%d")
        ov = await ctx.db.quiz_overview(since)
        return await render(request, "quiz.html", o=ov, days=days, s=ctx.settings, page="quiz",
                            notice=request.query_params.get("notice"))

    @app.post("/quiz/send-now", response_class=HTMLResponse)
    async def quiz_send_now(_: int = Depends(csrf_required)):
        n = await quiz_mod.send_all_now()
        return _hx("/quiz?notice=" + quote(f"Test {n} ta xodimga yuborildi."))

    @app.post("/quiz/prepare", response_class=HTMLResponse)
    async def quiz_prepare(_: int = Depends(csrf_required)):
        n = await quiz_mod.prepare_pools()
        return _hx("/quiz?notice=" + quote(f"{n} ta yangi savol tayyorlandi."))


    # ---------------- ommaviy e'lonlar ----------------
    @app.get("/announcements", response_class=HTMLResponse)
    async def announcements_page(request: Request, _: int = Depends(admin_required)):
        return await render(request, "announcements.html", items=await get_ctx().db.list_announcements(), page="announce",
                            notice=request.query_params.get("notice"))

    @app.get("/announcements/new", response_class=HTMLResponse)
    async def announcement_new(request: Request, copy: int = 0, _: int = Depends(admin_required)):
        ctx = get_ctx()
        users = await ctx.db.list_users("approved")
        src = (await ctx.db.get_announcement(copy)) if copy else None
        return await render(request, "announcement_new.html", users=users, roles=ROLES, page="announce", src=src)

    @app.post("/announcements/preview", response_class=HTMLResponse)
    async def announcement_preview(request: Request, admin_id: int = Depends(csrf_required)):
        form = await request.form()
        kind, title, text = str(form.get("kind", "info")), str(form.get("title", "")), str(form.get("text", ""))
        mode = str(form.get("aud_mode", "all"))
        aud = {"mode": mode if mode in ("all", "roles", "users") else "all",
               "roles": [str(x) for x in form.getlist("roles")],
               "users": [int(x) for x in form.getlist("users") if str(x).isdigit()]}
        data, name = None, "image.jpg"
        f = form.get("image")
        if f is not None and getattr(f, "filename", ""):
            ctype = f.content_type or mimetypes.guess_type(f.filename)[0] or ""
            if not ctype.startswith("image/"):
                return HTMLResponse('<span class="err">Faqat rasm (JPG/PNG) yuklash mumkin.</span>')
            data, name = await f.read(), f.filename
            if len(data) > MAX_IMAGE:
                return HTMLResponse(f'<span class="err">Rasm juda katta (chegara: {MAX_IMAGE // 1024 // 1024} MB).</span>')
        elif form.get("keep_image"):
            src = await get_ctx().db.get_announcement(int(form.get("keep_image") or 0))
            if src and src.get("image_file_id"):
                try:
                    fl = await get_ctx().bot.get_file(src["image_file_id"])
                    buf = await get_ctx().bot.download_file(fl.file_path)
                    data = buf.read() if hasattr(buf, "read") else bytes(buf)
                except TelegramAPIError:
                    return HTMLResponse('<span class="err">Eski rasmni olib bo\'lmadi, qayta yuklang.</span>')
        try:
            ann_id = await announce_mod.make_draft(kind, title, text, data, name, aud, bool(form.get("ack")), admin_id)
        except ValueError as exc:
            return HTMLResponse(f'<span class="err">{html.escape(str(exc))}</span>')
        return _hx(f"/announcements/{ann_id}")

    async def _ann_or_404(ann_id: int) -> dict:
        ann = await get_ctx().db.get_announcement(ann_id)
        if not ann:
            raise HTTPException(404, "E'lon topilmadi")
        return ann

    @app.get("/announcements/{ann_id}", response_class=HTMLResponse)
    async def announcement_page(request: Request, ann_id: int, _: int = Depends(admin_required)):
        ctx = get_ctx()
        ann = await _ann_or_404(ann_id)
        audience = await ctx.db.audience_users(ann["aud"])
        return await render(request, "announcement.html", a=ann, preview=announce_mod.render(ann), page="announce",
                            stats=await ctx.db.announcement_stats(ann_id), audience_n=len(audience),
                            recips=await ctx.db.announcement_recipients(ann_id), tz=ctx.settings.timezone,
                            notice=request.query_params.get("notice"))

    @app.get("/announcements/{ann_id}/stats", response_class=HTMLResponse)
    async def announcement_stats(request: Request, ann_id: int, _: int = Depends(admin_required)):
        ctx = get_ctx()
        ann = await _ann_or_404(ann_id)
        return await render(request, "_ann_stats.html", a=ann, stats=await ctx.db.announcement_stats(ann_id),
                            recips=await ctx.db.announcement_recipients(ann_id))

    @app.get("/announcements/{ann_id}/image")
    async def announcement_image(ann_id: int, _: int = Depends(admin_required)):
        ctx = get_ctx()
        ann = await _ann_or_404(ann_id)
        fid = ann.get("image_file_id")
        if not fid:
            raise HTTPException(404, "Rasm yo'q")
        headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
        cached = _cache.get(fid)
        if cached:
            return Response(cached[0], media_type=cached[1], headers=headers)
        try:
            f = await ctx.bot.get_file(fid)
            buf = await ctx.bot.download_file(f.file_path)
            data = buf.read() if hasattr(buf, "read") else bytes(buf)
        except TelegramAPIError:
            raise HTTPException(404, "Rasmni Telegramdan olib bo'lmadi")
        ctype = mimetypes.guess_type(f.file_path or "")[0] or "image/jpeg"
        _cache.put(fid, data, ctype)
        return Response(data, media_type=ctype, headers=headers)

    @app.post("/announcements/{ann_id}/send", response_class=HTMLResponse)
    async def announcement_send(ann_id: int, _: int = Depends(csrf_required)):
        await _ann_or_404(ann_id)
        ok = await announce_mod.start(ann_id)
        note = "Yuborish boshlandi." if ok else "Bu e'lon allaqachon yuborilgan yoki yuborilmoqda."
        return _hx(f"/announcements/{ann_id}?notice=" + quote(note))

    @app.post("/announcements/{ann_id}/schedule", response_class=HTMLResponse)
    async def announcement_schedule(ann_id: int, when: str = Form(""), _: int = Depends(csrf_required)):
        ctx = get_ctx()
        await _ann_or_404(ann_id)
        utc = announce_mod.to_utc(when, ctx.settings.timezone)
        if not utc:
            return HTMLResponse('<span class="err">Sana va vaqtni tanlang.</span>')
        if utc <= datetime.now(timezone.utc).strftime(FMT):
            return HTMLResponse('<span class="err">Vaqt kelajakda bo\'lishi kerak.</span>')
        if not await announce_mod.schedule(ann_id, utc):
            return HTMLResponse('<span class="err">Bu e\'lonni endi rejalashtirib bo\'lmaydi.</span>')
        return _hx(f"/announcements/{ann_id}?notice=" + quote("Rejalashtirildi."))

    @app.post("/announcements/{ann_id}/unschedule", response_class=HTMLResponse)
    async def announcement_unschedule(ann_id: int, _: int = Depends(csrf_required)):
        await announce_mod.unschedule(ann_id)
        return _hx(f"/announcements/{ann_id}?notice=" + quote("Rejalashtirish bekor qilindi."))

    @app.post("/announcements/{ann_id}/delete", response_class=HTMLResponse)
    async def announcement_delete(ann_id: int, _: int = Depends(csrf_required)):
        ann = await _ann_or_404(ann_id)
        if ann["status"] == "sending":
            return _hx(f"/announcements/{ann_id}?notice=" + quote("Yuborilayotgan e'lonni o'chirib bo'lmaydi."))
        await get_ctx().db.delete_announcement(ann_id)
        return _hx("/announcements?notice=" + quote("O'chirildi."))

    # ---------------- jonli hodisalar ----------------
    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        admin_id = ws.session.get("admin_id") if "session" in ws.scope else None
        if not admin_id or admin_id not in get_ctx().settings.admin_ids:
            await ws.close(code=4401)
            return
        await ws.accept()
        hub = get_ctx().hub
        await hub.register(ws)
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            await hub.unregister(ws)

    return app
