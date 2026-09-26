"""Yagona AI agent: bot ham, veb-panel ham (hisobot, video reja, javob taklifi) shu orqali ishlaydi.

Agent OpenAI Responses API va `file_search` (vector store) dan foydalanadi:
qo'llanmalar OpenAI vector store'da turadi, agent har savolda kerakli joyni qidirib javob beradi.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from .constants import TOPICS
from .config import Settings
from .format import clean_citations

log = logging.getLogger(__name__)

TOPIC_LIST = "; ".join(TOPICS)

ANSWER_INSTRUCTIONS = f"""Siz "Prof ta'lim" (kasb-emis) axborot tizimi bo'yicha texnikum xodimlariga yordam beradigan yordamchisiz.

Qoidalar:
1. Faqat file_search orqali topilgan qo'llanma mazmuniga tayaning. Menyu, tugma yoki qadamlarni o'zingizdan to'qimang.
2. Javobni o'zbek tilida (lotin yozuvida), qisqa, tartibli va aniq yozing (ko'pi bilan 8 qator). Qadamlar bo'lsa har birini yangi qatorda "1.", "2.", "3." shaklida yozing. Menyu, tugma va muhim iboralarni **qalin** qilib belgilang (faqat ikkita yulduzcha, boshqa markdown, sarlavha # va havolalar yo'q). Qo'llanmadan olingan fayl havolalari yoki [1] kabi belgilarni javobga qo'shmang.
3. Menyu va tugma nomlarini qo'llanmadagidek yozing.
4. Foydalanuvchining roli: {{role}}. Lekin u hamkasblari uchun boshqa rollarga tegishli savol ham berishi mumkin: har qanday rol bo'yicha savolga qo'llanmadan to'liq javob bering (rolga qarab javobni cheklamang). Faqat oxirida bu amalni qaysi rol bajarishini qisqa eslating.
5. Qo'llanmada aniq javob topilmasa yoki ishonchingiz komil bo'lmasa, found=false qiling va answer ni bo'sh qoldiring.
6. Shaxsiy ma'lumotlar ([PINFL], [PASPORT]) yashirilgan. Ularni so'ramang va takrorlamang.
7. Salomlashish yoki minnatdorchilik bo'lsa, qisqa muloyim javob bering (found=true, topic="Boshqa").
8. Savol tizimga aloqasiz bo'lsa, muloyimlik bilan faqat tizim bo'yicha yordam bera olishingizni ayting (found=true, topic="Boshqa").
9. Quyida "ADMIN TASDIQLAGAN JAVOBLAR" bo'lsa, savolga mos kelganda ularga tayaning: ular qo'llanmadan ustun. Bunda section="Admin javoblari bazasi".
10. Quyida "VIDEO DARSLAR" ro'yxati bo'lsa va savol mavzusiga aniq mos video bo'lsa, uning raqamini video_id ga yozing; mos bo'lmasa null.
{{kb}}{{videos}}
Javob formati: FAQAT bitta JSON obyekt, boshqa matn yozmang:
{{"found": true yoki false, "title": "javobning 2-6 so'zli qisqa sarlavhasi, masalan: Yangi o'quvchi qo'shish", "answer": "javob matni", "topic": "ro'yxatdagi mavzulardan biri", "section": "qo'llanma va bo'lim, masalan: O'quv bo'limi qo'llanmasi, 9.2", "video_id": raqam yoki null}}

Mavzular ro'yxati: {TOPIC_LIST}
"""

REPORT_INSTRUCTIONS = """Siz texnikum xodimlariga yordam beruvchi Telegram bot faoliyati bo'yicha hisobot tayyorlaydigan tahlilchisiz.
Sizga statistika (JSON) beriladi. O'zbek tilida (lotin) aniq, qisqa va amaliy hisobot yozing. Faqat berilgan raqamlarga tayaning, raqam to'qimang.
Tuzilma (Markdown):
## Asosiy xulosa (2-4 jumla)
## Ko'rsatkichlar (qisqa jadval yoki ro'yxat)
## Eng ko'p so'ralgan mavzular va sabablari
## Muammoli joylar (javobsiz savollar)
## Tavsiyalar (xodimlarni o'rgatish, qo'llanmani yaxshilash, video rolik mavzulari)
Agar ma'lumot kam bo'lsa, buni halol yozing."""

VIDEO_INSTRUCTIONS = """Siz texnikum xodimlari uchun "Prof ta'lim" axborot tizimi bo'yicha qisqa o'quv video roliklar rejalashtiradigan metodistsiz.
Sizga xodimlar bergan real savollar (shaxsiy ma'lumotlar yashirilgan) va mavzu beriladi. file_search orqali qo'llanmadan kerakli bo'limlarni toping va O'ZBEK tilida (lotin) video rolik uchun TO'LIQ material tayyorlang. Qadamlarni faqat qo'llanmaga tayanib yozing, to'qimang.
Markdown tuzilma:
# Video rolik: <sarlavha>
## Maqsad va auditoriya (qaysi rol, nimani o'rganadi)
## Davomiylik (3-6 daqiqa)
## Nima uchun bu rolik kerak (real savollar asosida, qisqa)
## Ssenariy (jadval: № | Ekranda nima ko'rsatiladi | Ovozli matn (o'zbekcha) | Vaqt)
## Qadamma-qadam amallar (menyu va tugma nomlari bilan)
## Ko'p uchraydigan xatolar va yechimlari
## Tayyorlash uchun materiallar (kerakli skrinshotlar ro'yxati, demo ma'lumotlar, test texnikumda oldindan tayyorlanadigan holatlar)
## Ekrandagi yozuvlar / subtitr takliflari
## Tekshiruv savollari (3-5 ta)
## Manba: qo'llanma va bo'limlar
Rolik oxirida qisqa xulosa va Telegram botdan yordam olish haqida eslatma bo'lsin."""

SUGGEST_INSTRUCTIONS = """Siz texnikum xodimiga javob yozayotgan admin uchun javob loyihasini tayyorlaysiz.
file_search orqali qo'llanmadan foydalaning. O'zbek tilida (lotin), qisqa (ko'pi bilan 6 qator), xushmuomala va aniq yozing. Oddiy matn, muhim iboralar **qalin**. Fayl havolalarini qo'shmang.
Faqat javob matnining o'zini yozing. Qo'llanmada ma'lumot topilmasa, buni ayting va admin aniqlashtirishi kerakligini yozing."""


QUIZ_INSTRUCTIONS = """Siz "Prof ta'lim" (kasb-emis) tizimi bo'yicha xodimlar uchun kunlik test (viktorina) savollarini tuzasiz.
Sizga rol, manba (qaysi qo'llanma) va kerakli savollar soni beriladi. file_search orqali shu qo'llanmadan foydalaning.
Qoidalar:
1. Faqat qo'llanmada bor ma'lumotga tayanib savol tuzing. To'qimang.
2. Har savolda aynan 3 ta variant va bitta to'g'ri javob. Noto'g'ri variantlar ishonarli, lekin aniq noto'g'ri bo'lsin. Variantlar uzunligi o'xshash bo'lsin.
3. Savollar amaliy bo'lsin (qaysi menyu, qaysi tugma, qaysi tartib, kim bajaradi). Shaxsiy ma'lumot ishlatmang.
4. "quyidagi_savollarni_takrorlama" ro'yxatidagi savollar bilan bir xil yoki juda o'xshash savol tuzmang.
5. O'zbek tilida (lotin). Savol 1-2 jumla, variantlar qisqa. Fayl havolalari yoki [1] kabi belgilarni yozmang.
Javob formati: FAQAT bitta JSON obyekt:
{"questions": [{"question": "...", "options": ["A variant", "B variant", "C variant"], "correct": 0 yoki 1 yoki 2, "explanation": "1 jumlali izoh", "topic": "mavzular ro'yxatidan biri", "source": "qo'llanma va bo'lim"}]}"""

FAQ_INSTRUCTIONS = """Siz texnikum xodimlarining bot bilan yozishmalarini tahlil qilib, "Ko'p so'raladigan savollar" (FAQ) ro'yxatini tuzasiz.
Sizga real savol-javoblar (shaxsiy ma'lumotlar yashirilgan) va allaqachon mavjud FAQ savollari (id bilan) beriladi.
Qoidalar:
1. Ma'no jihatidan bir xil savollarni bitta guruhga birlashtiring. Faqat kamida 2 marta so'ralgan yoki muhim amaliy savollarni oling.
2. FAQ savoli qisqa va umumiy bo'lsin (masalan: "O'quvchini guruhga qanday biriktiraman?"). Javobni FAQAT berilgan bot javoblariga tayanib, qisqa va tartibli yozing (qadamlar "1.", "2." shaklida, menyu/tugma nomlari **qalin**). Yangi ma'lumot to'qimang.
3. Guruh mavjud FAQ bilan bir xil bo'lsa, "match_id" ga o'sha id ni yozing (yangisini yaratmang), "count" ni yangilang.
4. Shaxsiy ma'lumot yozmang. O'zbek tilida (lotin).
Javob formati: FAQAT bitta JSON obyekt:
{"faq": [{"question": "...", "answer": "...", "topic": "mavzular ro'yxatidan biri", "count": son, "match_id": id yoki null}]}"""


class AgentError(RuntimeError):
    pass


@dataclass
class AgentAnswer:
    found: bool
    answer: str
    topic: str = "Boshqa"
    section: str = ""
    title: str = ""
    video_id: int | None = None
    sources: list[str] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0


def _extract_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S).strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, flags=re.S)
    if m:
        try:
            data = json.loads(m.group(0))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _norm_topic(topic: str | None) -> str:
    if not topic:
        return "Boshqa"
    t = topic.strip().lower()
    for known in TOPICS:
        if known.lower() == t:
            return known
    for known in TOPICS:
        if t and (t in known.lower() or known.lower() in t):
            return known
    return "Boshqa"


class TexnikumAgent:
    def __init__(self, settings: Settings, client: Any | None = None):
        self.s = settings
        if client is not None:
            self.client = client
        else:
            from openai import AsyncOpenAI

            self.client = AsyncOpenAI(api_key=settings.openai_api_key or "missing", timeout=90, max_retries=2)

    # ---------- past daraja ----------
    async def _call(self, *, instructions: str, messages: list[dict[str, str]], model: str, use_search: bool,
                    max_output_tokens: int, purpose: str = "other") -> tuple[str, list[str], int, int]:
        if not self.s.openai_api_key and not hasattr(self.client, "_is_fake"):
            raise AgentError("OPENAI_API_KEY sozlanmagan")
        kwargs: dict[str, Any] = dict(
            model=model,
            instructions=instructions,
            input=messages,
            store=False,
            max_output_tokens=max_output_tokens,
        )
        if use_search and self.s.vector_store_id:
            kwargs["tools"] = [{"type": "file_search", "vector_store_ids": [self.s.vector_store_id],
                                "max_num_results": 8}]
        try:
            resp = await self.client.responses.create(**kwargs)
        except Exception as exc:  # noqa: BLE001
            log.exception("OpenAI so'rovi xato berdi")
            from . import ops

            await ops.record_usage(purpose, model, 0, 0, ok=False, error=str(exc))
            raise AgentError(str(exc)) from exc
        text = clean_citations(getattr(resp, "output_text", None) or "")
        sources: list[str] = []
        for item in getattr(resp, "output", None) or []:
            if getattr(item, "type", "") != "message":
                continue
            for part in getattr(item, "content", None) or []:
                for ann in getattr(part, "annotations", None) or []:
                    if getattr(ann, "type", "") == "file_citation":
                        name = getattr(ann, "filename", None)
                        if name and name not in sources:
                            sources.append(name)
        usage = getattr(resp, "usage", None)
        tin, tout = int(getattr(usage, "input_tokens", 0) or 0), int(getattr(usage, "output_tokens", 0) or 0)
        from . import ops

        await ops.record_usage(purpose, model, tin, tout)
        return (text, sources, tin, tout)

    async def ping(self) -> str:
        """Ulanishni tekshiradi (vector store'ni o'qiydi, token sarflamaydi)."""
        if hasattr(self.client, "_is_fake"):
            return "ok"
        from .kb import _vs_api

        await _vs_api(self.client).retrieve(self.s.vector_store_id)
        return "ok"

    # ---------- bot uchun ----------
    async def answer(self, question: str, role: str | None, history: list[dict],
                     kb: list[dict] | None = None, videos: list[dict] | None = None) -> AgentAnswer:
        """Savolga qo'llanma asosida javob. `question` va `history` allaqachon shaxsiy ma'lumotdan tozalangan bo'lishi shart."""
        msgs: list[dict[str, str]] = []
        for h in history:
            role_name = "assistant" if h["sender"] == "bot" else "user"
            msgs.append({"role": role_name, "content": h["text"]})
        msgs.append({"role": "user", "content": question})
        kb_block = ""
        if kb:
            kb_block = "\nADMIN TASDIQLAGAN JAVOBLAR:\n" + "\n".join(
                f"- Savol: {e['question']}\n  Javob: {e['answer']}" for e in kb[:3]) + "\n"
        video_block = ""
        if videos:
            video_block = "\nVIDEO DARSLAR (raqam | sarlavha | mavzu | kalit so'zlar):\n" + "\n".join(
                f"{v['id']} | {v['title']} | {v.get('topic') or ''} | {v.get('keywords') or ''}" for v in videos[:60]) + "\n"
        instructions = (ANSWER_INSTRUCTIONS.replace("{role}", role or "noma'lum")
                        .replace("{kb}", kb_block).replace("{videos}", video_block))
        text, sources, tin, tout = await self._call(
            instructions=instructions, messages=msgs, model=self.s.model, use_search=True, max_output_tokens=3000, purpose="answer")
        data = _extract_json(text)
        if data is None:
            clean = text.strip()
            if not clean:
                raise AgentError("Model bo'sh javob qaytardi")
            return AgentAnswer(found=True, answer=clean_citations(clean), topic="Boshqa", sources=sources, tokens_in=tin, tokens_out=tout)
        found = bool(data.get("found", True))
        answer = clean_citations(str(data.get("answer") or ""))
        if found and not answer:
            found = False
        vid = data.get("video_id")
        valid = {v["id"] for v in (videos or [])}
        try:
            vid = int(vid) if vid is not None else None
        except (TypeError, ValueError):
            vid = None
        if vid not in valid:
            vid = None
        return AgentAnswer(found=found, answer=answer, topic=_norm_topic(data.get("topic")), video_id=vid,
                           section=clean_citations(str(data.get("section") or "")),
                           title=clean_citations(str(data.get("title") or "")), sources=sources, tokens_in=tin, tokens_out=tout)

    # ---------- veb-panel uchun ----------
    async def suggest_reply(self, conversation: list[dict]) -> str:
        lines = []
        for m in conversation[-12:]:
            who = {"user": "Xodim", "bot": "Bot", "admin": "Admin"}.get(m["sender"], m["sender"])
            if m["kind"] != "text" or not m.get("text"):
                lines.append(f"{who}: [{m['kind']}]")
            else:
                lines.append(f"{who}: {m['text']}")
        text, _, _, _ = await self._call(
            instructions=SUGGEST_INSTRUCTIONS, messages=[{"role": "user", "content": "\n".join(lines)}],
            model=self.s.model, use_search=True, max_output_tokens=2000, purpose="suggest")
        return text.strip()

    async def report_summary(self, label: str, stats: dict, samples: dict) -> str:
        payload = json.dumps({"davr": label, "statistika": stats, "namuna_savollar": samples}, ensure_ascii=False)
        text, _, _, _ = await self._call(
            instructions=REPORT_INSTRUCTIONS, messages=[{"role": "user", "content": payload}],
            model=self.s.report_model, use_search=False, max_output_tokens=6000, purpose="report")
        return text.strip()

    async def video_plan(self, topic: str, roles: list[str], questions: list[dict]) -> str:
        qs = [{"savol": q["text"], "bot_javobi": (q.get("bot_answer") or "")[:400], "topilmadi": q.get("found") == 0,
               "baho": q.get("feedback")} for q in questions[:20]]
        payload = json.dumps({"mavzu": topic, "rollar": roles, "real_savollar": qs}, ensure_ascii=False)
        text, _, _, _ = await self._call(
            instructions=VIDEO_INSTRUCTIONS, messages=[{"role": "user", "content": payload}],
            model=self.s.report_model, use_search=True, max_output_tokens=8000, purpose="video_plan")
        return text.strip()


    # ---------- viktorina va FAQ ----------
    async def quiz_questions(self, role: str, n: int, avoid: list[str]) -> list[dict]:
        from .constants import ROLE_GUIDES

        guide = ROLE_GUIDES.get(role, ROLE_GUIDES["Boshqa"])
        payload = json.dumps({"rol": role, "manba": guide, "savollar_soni": n,
                              "quyidagi_savollarni_takrorlama": avoid[-60:], "mavzular": TOPIC_LIST}, ensure_ascii=False)
        text, _, _, _ = await self._call(instructions=QUIZ_INSTRUCTIONS, messages=[{"role": "user", "content": payload}],
                                         model=self.s.model, use_search=True, max_output_tokens=6000, purpose="quiz")
        data = _extract_json(text) or {}
        items = data.get("questions") or []
        out = []
        for it in items if isinstance(items, list) else []:
            if isinstance(it, dict):
                it["topic"] = _norm_topic(it.get("topic"))
                for k in ("question", "explanation", "source"):
                    if k in it:
                        it[k] = clean_citations(str(it[k]))
                it["options"] = [clean_citations(str(o)) for o in it.get("options", [])]
                out.append(it)
        return out

    async def faq_clusters(self, items: list[dict], existing: list[dict]) -> list[dict]:
        payload = json.dumps({"savol_javoblar": items, "mavjud_faq": existing, "mavzular": TOPIC_LIST}, ensure_ascii=False)
        text, _, _, _ = await self._call(instructions=FAQ_INSTRUCTIONS, messages=[{"role": "user", "content": payload}],
                                         model=self.s.report_model, use_search=False, max_output_tokens=6000, purpose="faq")
        data = _extract_json(text) or {}
        res = data.get("faq") or []
        return [r for r in res if isinstance(r, dict)] if isinstance(res, list) else []
