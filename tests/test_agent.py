from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent import AgentError, TexnikumAgent, _extract_json, _norm_topic
from app.config import Settings


class FakeResponses:
    def __init__(self, text, sources=(), usage=(10, 5), raises=None):
        self.text, self.sources, self.usage, self.raises = text, sources, usage, raises
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        if self.raises:
            raise self.raises
        ann = [SimpleNamespace(type="file_citation", filename=n) for n in self.sources]
        item = SimpleNamespace(type="message", content=[SimpleNamespace(annotations=ann)])
        return SimpleNamespace(output_text=self.text, output=[SimpleNamespace(type="file_search_call"), item],
                               usage=SimpleNamespace(input_tokens=self.usage[0], output_tokens=self.usage[1]))


def make(text, **kw):
    s = Settings(openai_api_key="k", vector_store_id="vs_1", model="gpt-6-luna", report_model="gpt-6-sol")
    resp = FakeResponses(text, **kw)
    return TexnikumAgent(s, client=SimpleNamespace(responses=resp)), resp


def test_extract_json_variants():
    assert _extract_json('{"a": 1}') == {"a": 1}
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert _extract_json('Mana javob: {"a": 1} tamom') == {"a": 1}
    assert _extract_json("umuman json emas") is None
    assert _extract_json("[1, 2]") is None


def test_norm_topic():
    assert _norm_topic("Elektron jurnal") == "Elektron jurnal"
    assert _norm_topic("elektron JURNAL") == "Elektron jurnal"
    assert _norm_topic("jurnal") == "Elektron jurnal"
    assert _norm_topic("umuman boshqa narsa") == "Boshqa"
    assert _norm_topic(None) == "Boshqa"


async def test_answer_parses_json_sources_and_request_shape():
    agent, resp = make('```json\n{"found": true, "answer": "1. Bosing", "topic": "Guruhlar", "section": "O\'quv bo\'limi, 10.2"}\n```',
                       sources=["O_quv_bo_limi.txt", "O_quv_bo_limi.txt", "Super_admin.txt"], usage=(1200, 80))
    res = await agent.answer("Guruh qanday ochiladi?", "O'quv bo'limi", [{"sender": "user", "text": "salom"},
                                                                       {"sender": "bot", "text": "assalomu alaykum"}])
    assert res.found and res.answer == "1. Bosing" and res.topic == "Guruhlar" and res.section == "O'quv bo'limi, 10.2"
    assert res.sources == ["O_quv_bo_limi.txt", "Super_admin.txt"] and (res.tokens_in, res.tokens_out) == (1200, 80)
    k = resp.kwargs
    assert k["model"] == "gpt-6-luna" and k["store"] is False
    assert k["tools"] == [{"type": "file_search", "vector_store_ids": ["vs_1"], "max_num_results": 8}]
    assert [m["role"] for m in k["input"]] == ["user", "assistant", "user"] and k["input"][-1]["content"] == "Guruh qanday ochiladi?"
    assert "O'quv bo'limi" in k["instructions"] and "{role}" not in k["instructions"]


async def test_answer_not_found_and_empty_answer():
    agent, _ = make('{"found": false, "answer": "", "topic": "Diplomlar"}')
    r = await agent.answer("savol", None, [])
    assert r.found is False and r.topic == "Diplomlar"
    agent, _ = make('{"found": true, "answer": "  ", "topic": "Diplomlar"}')
    assert (await agent.answer("savol", None, [])).found is False


async def test_answer_plain_text_fallback_and_empty():
    agent, _ = make("Oddiy matn javob")
    r = await agent.answer("savol", None, [])
    assert r.found and r.answer == "Oddiy matn javob" and r.topic == "Boshqa"
    agent, _ = make("   ")
    with pytest.raises(AgentError):
        await agent.answer("savol", None, [])


async def test_api_errors_become_agent_error():
    agent, _ = make("", raises=RuntimeError("boom"))
    with pytest.raises(AgentError):
        await agent.answer("savol", None, [])


async def test_missing_key_raises():
    s = Settings(openai_api_key="", vector_store_id="vs_1")
    agent = TexnikumAgent(s, client=SimpleNamespace(responses=FakeResponses("x")))
    with pytest.raises(AgentError):
        await agent.answer("savol", None, [])


async def test_report_and_video_use_report_model():
    agent, resp = make("## Xulosa")
    await agent.report_summary("bugun", {"questions": 1}, {})
    assert resp.kwargs["model"] == "gpt-6-sol" and "tools" not in resp.kwargs
    await agent.video_plan("Guruhlar", ["O'quv bo'limi"], [{"text": "q", "found": 0}])
    assert resp.kwargs["model"] == "gpt-6-sol" and resp.kwargs["tools"][0]["type"] == "file_search"
