from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage

from app import events
from app.config import Settings
from app.llm.router import FALLBACK, ROUTES, LLMUnavailableError, RoutedLLM


class FakeModel:
    def __init__(self, text: str = "ok", fail: bool = False, fail_after_tokens: int | None = None):
        self.text, self.fail, self.fail_after_tokens = text, fail, fail_after_tokens
        self.calls = 0

    async def ainvoke(self, messages):
        self.calls += 1
        if self.fail:
            raise ConnectionError("boom")
        return AIMessage(self.text, usage_metadata={"input_tokens": 3, "output_tokens": 2, "total_tokens": 5})

    async def astream(self, messages) -> AsyncIterator[AIMessageChunk]:
        self.calls += 1
        if self.fail:
            raise ConnectionError("boom")
        for i, word in enumerate(self.text.split(" ")):
            if self.fail_after_tokens is not None and i >= self.fail_after_tokens:
                raise ConnectionError("mid-stream")
            yield AIMessageChunk(word + " ")


@pytest.fixture
def captured(monkeypatch):
    seen: list[tuple[str, str, dict]] = []
    monkeypatch.setattr("app.llm.router.trace", lambda kind, node, **d: seen.append(("trace", kind, d)))
    monkeypatch.setattr("app.llm.router.token", lambda text, node: seen.append(("token", text, {})))
    return seen


def make_llm(models: dict[str, FakeModel]) -> RoutedLLM:
    return RoutedLLM(Settings(_env_file=None), factory=lambda settings, provider: models[provider])


def test_routing_table_uses_three_distinct_providers() -> None:
    assert {route.provider for route in ROUTES.values()} == {"openai", "gemini", "deepseek"}
    for agent, route in ROUTES.items():
        assert route.reason, agent
        assert FALLBACK[agent] != route.provider


async def test_primary_success_records_route_and_usage(captured) -> None:
    models = {"openai": FakeModel("hello"), "gemini": FakeModel(), "deepseek": FakeModel()}
    reply = await make_llm(models).call("research", [HumanMessage("q")])
    assert reply.text == "hello"
    assert reply.provider == "openai" and reply.fallback is False
    kinds = [item[1] for item in captured if item[0] == "trace"]
    assert kinds == ["llm_route", "llm_done"]
    assert captured[-1][2]["output_tokens"] == 2


async def test_primary_failure_falls_back_and_is_visible(captured) -> None:
    models = {"openai": FakeModel(fail=True), "gemini": FakeModel("from gemini"), "deepseek": FakeModel()}
    reply = await make_llm(models).call("research", [HumanMessage("q")])
    assert reply.provider == "gemini" and reply.fallback is True
    routes = [item[2] for item in captured if item[1] == "llm_route"]
    assert routes[1]["fallback"] is True
    assert "ConnectionError" in routes[1]["reason"]


async def test_provider_error_text_is_not_sent_to_clients(captured) -> None:
    models = {"openai": FakeModel(fail=True), "gemini": FakeModel(fail=True), "deepseek": FakeModel()}
    with pytest.raises(LLMUnavailableError) as info:
        await make_llm(models).call("research", [HumanMessage("q")])
    routes = [item[2] for item in captured if item[1] == "llm_route"]
    assert routes[1]["reason"] == "primary openai failed: ConnectionError"
    assert "boom" not in str(info.value)


async def test_backup_kimi_answers_when_primary_and_fallback_fail(captured) -> None:
    models = {"openai": FakeModel(fail=True), "gemini": FakeModel(fail=True), "deepseek": FakeModel(),
              "kimi": FakeModel("from kimi")}
    llm = RoutedLLM(Settings(_env_file=None, kimi_api_key="k"), factory=lambda settings, provider: models[provider])
    reply = await llm.call("research", [HumanMessage("q")])
    assert reply.provider == "kimi" and reply.fallback is True and reply.text == "from kimi"
    routes = [item[2] for item in captured if item[1] == "llm_route"]
    assert [r["provider"] for r in routes] == ["openai", "gemini", "kimi"]
    assert [r["tier"] for r in routes] == [0, 1, 2]
    assert routes[2]["reason"] == "fallback gemini failed: ConnectionError; last-resort backup after primary and fallback failed"


async def test_backup_is_skipped_without_kimi_key(captured) -> None:
    models = {"openai": FakeModel(fail=True), "gemini": FakeModel(fail=True), "deepseek": FakeModel(),
              "kimi": FakeModel("from kimi")}
    with pytest.raises(LLMUnavailableError):
        await make_llm(models).call("research", [HumanMessage("q")])
    assert models["kimi"].calls == 0


async def test_streaming_emits_tokens(captured) -> None:
    models = {"openai": FakeModel("a b c"), "gemini": FakeModel(), "deepseek": FakeModel()}
    reply = await make_llm(models).call("research", [HumanMessage("q")], stream=True)
    assert [item[1] for item in captured if item[0] == "token"] == ["a ", "b ", "c "]
    assert reply.text == "a b c "


async def test_no_fallback_after_tokens_were_streamed(captured) -> None:
    models = {"openai": FakeModel("a b c", fail_after_tokens=1), "gemini": FakeModel(), "deepseek": FakeModel()}
    with pytest.raises(LLMUnavailableError):
        await make_llm(models).call("research", [HumanMessage("q")], stream=True)
    assert models["gemini"].calls == 0


async def test_both_providers_failing_raises(captured) -> None:
    models = {"openai": FakeModel(fail=True), "gemini": FakeModel(fail=True), "deepseek": FakeModel()}
    with pytest.raises(LLMUnavailableError):
        await make_llm(models).call("research", [HumanMessage("q")])


from app.llm.router import ROUTES as _ROUTES


@pytest.mark.integration
@pytest.mark.parametrize("agent", ["supervisor", "research", "summary"])  # covers gemini / openai / deepseek
@pytest.mark.parametrize("stream", [False, True])
async def test_real_provider_answers_without_fallback(agent, stream, monkeypatch) -> None:
    seen: list[dict] = []
    monkeypatch.setattr("app.llm.router.trace", lambda kind, node, **d: seen.append({"kind": kind, **d}))
    reply = await RoutedLLM(Settings()).call(agent, [HumanMessage("Reply with the single word: pong")], stream=stream)
    assert "pong" in reply.text.lower()
    assert reply.fallback is False and reply.provider == _ROUTES[agent].provider
    done = [d for d in seen if d["kind"] == "llm_done"][0]
    assert done["input_tokens"] > 0 and done["output_tokens"] > 0, "usage metadata missing"


@pytest.mark.integration
@pytest.mark.parametrize("stream", [False, True])
async def test_real_kimi_backup_answers(stream) -> None:
    from app.llm.providers import build_chat_model
    model = build_chat_model(Settings(), "kimi")
    if stream:
        text = "".join([chunk.content async for chunk in model.astream([HumanMessage("Reply with the single word: pong")])])
    else:
        text = (await model.ainvoke([HumanMessage("Reply with the single word: pong")])).content
    assert "pong" in text.lower()
