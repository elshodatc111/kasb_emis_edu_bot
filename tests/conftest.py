from __future__ import annotations

import io
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import GetFile, GetMe, SendMessage, SendPhoto, SendVideo
from aiogram.types import Chat, File, Message, PhotoSize, Update, User, Video

from app.agent import AgentAnswer, AgentError, TexnikumAgent
from app.bot import build_dispatcher
from app.config import Settings
from app.context import Context, set_ctx
from app.db import Database
from app.hub import Hub

ADMIN = 1000
EMP = 2000


class FakeSession(BaseSession):
    """Telegram'ga chiqmaydi: barcha chaqiruvlarni yozib oladi."""

    def __init__(self):
        super().__init__()
        self.calls: list = []
        self._mid = 100

    async def close(self):
        pass

    def _msg(self, chat_id, **kw):
        self._mid += 1
        return Message(message_id=self._mid, date=datetime.now(timezone.utc),
                       chat=Chat(id=int(chat_id), type="private"), **kw)

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, SendMessage):
            return self._msg(method.chat_id, text=method.text)
        if isinstance(method, SendPhoto):
            return self._msg(method.chat_id, photo=[PhotoSize(file_id="PH_SENT", file_unique_id="u", width=1, height=1)])
        if isinstance(method, SendVideo):
            return self._msg(method.chat_id, video=Video(file_id="VID_SENT", file_unique_id="v", width=1, height=1, duration=1))
        if isinstance(method, GetMe):
            return User(id=123456, is_bot=True, first_name="Bot", username="texnikum_test_bot")
        if isinstance(method, GetFile):
            return File(file_id=method.file_id, file_unique_id="x", file_path=f"photos/{method.file_id}.jpg")
        return True

    async def stream_content(self, url, headers=None, timeout=30, chunk_size=65536, raise_for_status=True):
        yield b"FAKE-IMAGE-BYTES"

    def sent(self, kind=SendMessage):
        return [c for c in self.calls if isinstance(c, kind)]

    def texts_to(self, chat_id):
        return [c.text for c in self.sent(SendMessage) if c.chat_id == chat_id]


class FakeAgent(TexnikumAgent):
    """OpenAI'ga chiqmaydi."""

    def __init__(self, settings):
        self.s = settings
        self.client = SimpleNamespace(_is_fake=True)
        self.answers: list = []
        self.questions: list[str] = []
        self.histories: list = []
        self.reports: list = []
        self.videos: list = []
        self.next = AgentAnswer(found=True, answer="1. Menyudan 'Elektron jurnal' ni tanlang.", topic="Elektron jurnal",
                                section="O'qituvchi qo'llanmasi, 5", sources=["O_qituvchi.txt"], tokens_in=100, tokens_out=20)

    async def answer(self, question, role, history, kb=None, videos=None):
        self.questions.append(question)
        self.histories.append(history)
        self.kb_seen = kb
        self.videos_seen = videos
        if isinstance(self.next, Exception):
            raise self.next
        return self.next

    async def quiz_questions(self, role, n, avoid):
        self.quiz_calls = getattr(self, "quiz_calls", 0) + 1
        base = self.quiz_calls * 100
        return [{"question": f"{role} savol {base + i}?", "options": [f"a{i}", f"b{i}", f"c{i}"], "correct": i % 3,
                 "explanation": "Izoh.", "topic": "Guruhlar", "source": "Qo'llanma"} for i in range(n)]

    async def faq_clusters(self, items, existing):
        self.faq_input = (items, existing)
        return getattr(self, "faq_result", [])

    async def suggest_reply(self, conversation):
        return "Taklif qilingan javob <b>"

    async def report_summary(self, label, stats, samples):
        self.reports.append((label, stats, samples))
        return "## Asosiy xulosa\nHammasi yaxshi."

    async def video_plan(self, topic, roles, questions):
        self.videos.append((topic, roles, questions))
        return f"# Video rolik: {topic} bo'yicha qo'llanma\n## Maqsad\nTest."


@pytest.fixture
async def ctx(tmp_path):
    settings = Settings(bot_token="123456:TEST", admin_ids=[ADMIN], openai_api_key="k", vector_store_id="vs_test",
                        base_url="http://panel.test", secret_key="s" * 32, rate_limit_per_min=3)
    db = Database(":memory:")
    await db.connect()
    session = FakeSession()
    bot = Bot(token="123456:TEST", session=session)
    agent = FakeAgent(settings)
    c = Context(settings=settings, db=db, bot=bot, agent=agent, hub=Hub())
    set_ctx(c)
    from app.bot import handlers

    handlers._rate.clear()
    from app import spam

    spam.clear()
    c.session = session  # type: ignore[attr-defined]
    yield c
    await db.close()


class Tg:
    """Botga soxta Telegram yangilanishlarini yuboradi."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.dp = build_dispatcher()
        self._uid = 0

    def _user(self, uid):
        return User(id=uid, is_bot=False, first_name="Ali", last_name="Valiyev", username=f"u{uid}")

    async def send(self, uid, **kw):
        self._uid += 1
        msg = Message(message_id=self._uid, date=datetime.now(timezone.utc), chat=Chat(id=uid, type="private"),
                      from_user=self._user(uid), **kw)
        await self.dp.feed_update(self.ctx.bot, Update(update_id=self._uid, message=msg))

    async def text(self, uid, text):
        await self.send(uid, text=text)

    async def photo(self, uid, caption=None):
        await self.send(uid, photo=[PhotoSize(file_id="PHOTO_FILE", file_unique_id="p", width=10, height=10)],
                        caption=caption)

    async def callback(self, uid, data, message_text="x"):
        from aiogram.types import CallbackQuery

        self._uid += 1
        m = Message(message_id=self._uid, date=datetime.now(timezone.utc), chat=Chat(id=uid, type="private"),
                    text=message_text)
        cb = CallbackQuery(id=str(self._uid), from_user=self._user(uid), chat_instance="ci", message=m, data=data)
        await self.dp.feed_update(self.ctx.bot, Update(update_id=self._uid, callback_query=cb))

    async def register(self, uid=EMP, role_idx=0):
        await self.text(uid, "/start")
        await self.text(uid, "Valiyev Ali Karimovich")
        await self.text(uid, "+998901234567")
        await self.text(uid, "Toshkent transport texnikumi")
        await self.callback(uid, f"role:{role_idx}")


@pytest.fixture
def tg(ctx):
    return Tg(ctx)
