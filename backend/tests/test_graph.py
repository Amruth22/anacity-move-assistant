"""The graph drives the SSE contract the browser depends on.

No model is called here. A scripted chat model stands in for the provider so
the frame order is deterministic: a tool must be announced before it runs,
a staged request must raise the confirm card, and every turn must close with
exactly one done.
"""

import asyncio
import json
from typing import Any, Iterator

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGenerationChunk

from app.agent import graph as graph_module
from app.agent import resident_agent
from app.sessions import create_session
from app.store import store


class ScriptedModel(BaseChatModel):
    """Replays a fixed script, one list of chunks per round."""

    turns: list = []
    calls: int = 0

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        chunks = self.turns[self.calls]
        self.calls += 1
        for chunk in chunks:
            generation = ChatGenerationChunk(message=chunk)
            if run_manager:
                run_manager.on_llm_new_token(chunk.text, chunk=generation)
            yield generation

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise NotImplementedError("streaming only")

    @property
    def _llm_type(self) -> str:
        return "scripted"


def tool_call_turn(name: str, args: dict, call_id: str = "call-1"):
    return [AIMessageChunk(
        content="",
        tool_call_chunks=[{
            "name": name,
            "args": json.dumps(args),
            "id": call_id,
            "index": 0,
        }],
    )]


def text_turn(*parts: str):
    return [AIMessageChunk(content=part) for part in parts]


@pytest.fixture(autouse=True)
def fresh_store():
    store.seed()
    yield
    store.seed()


def collect(session, message, script, monkeypatch):
    """Run one turn against the scripted model and return the parsed frames."""
    model = ScriptedModel(turns=script)
    monkeypatch.setattr(graph_module, "bound_model", lambda: model)

    async def drive():
        frames = []
        async for raw in resident_agent.run_turn(session, message):
            event = raw.split("\n")[0].removeprefix("event: ")
            data = json.loads(raw.split("data: ", 1)[1].strip())
            frames.append((event, data))
        return frames

    return asyncio.run(drive())


def priya_session():
    resident = next(r for r in store.residents.values() if r["name"] == "Priya Nair")
    return create_session(resident["id"], resident["community_id"])


def test_plain_answer_streams_text_then_done(monkeypatch):
    session = priya_session()

    frames = collect(session, "hello", [text_turn("Hi ", "Priya.")], monkeypatch)

    assert [e for e, _ in frames] == ["text", "text", "done"]
    assert "".join(d["delta"] for e, d in frames if e == "text") == "Hi Priya."


def test_a_tool_is_announced_before_it_runs(monkeypatch):
    session = priya_session()

    frames = collect(
        session,
        "what are the rules?",
        [tool_call_turn("get_community_policy", {"topic": "move_out"}), text_turn("Here they are.")],
        monkeypatch,
    )

    events = [e for e, _ in frames]
    assert events == ["tool", "text", "done"]
    assert frames[0][1]["name"] == "get_community_policy"
    assert frames[0][1]["label"] == "Checking community policy"


def test_staging_a_request_raises_the_confirm_card(monkeypatch):
    """The autonomy boundary: the model prepares, the card asks the human."""
    session = priya_session()
    resident = store.resident(session.resident_id)

    frames = collect(
        session,
        "book my move out",
        [
            tool_call_turn("create_move_request", {
                "request_type": "move_out",
                "unit_id": resident["unit_id"],
                "requested_date": "2026-12-14",
                "time_window": "10:00-12:00",
                "custom_field_answers": {"mover_company": "SafeShift", "forwarding_address": "18 MG Road"},
            }),
            text_turn("Ready when you are."),
        ],
        monkeypatch,
    )

    events = [e for e, _ in frames]
    assert events.index("tool") < events.index("confirm")
    assert events[-1] == "done"

    summary = next(d["summary"] for e, d in frames if e == "confirm")
    assert summary["requested_date"] == "2026-12-14"
    # staged, not filed: nothing exists until the human taps Confirm
    assert session.pending_draft is not None
    assert store.requests_for_resident(resident["id"]) == [] or all(
        r["requested_date"] != "2026-12-14" for r in store.requests_for_resident(resident["id"])
    )


def test_every_turn_closes_with_exactly_one_done(monkeypatch):
    session = priya_session()

    frames = collect(
        session,
        "check twice",
        [
            tool_call_turn("get_my_units", {}, "c1"),
            tool_call_turn("get_my_requests", {}, "c2"),
            text_turn("All set."),
        ],
        monkeypatch,
    )

    assert [e for e, _ in frames].count("done") == 1
    assert frames[-1][0] == "done"


def test_a_provider_failure_becomes_an_error_frame(monkeypatch):
    """A torn stream locks the input box forever. An error frame does not."""
    session = priya_session()

    class Exploding:
        async def astream(self, messages):
            raise RuntimeError("provider down")
            yield  # pragma: no cover

    monkeypatch.setattr(graph_module, "bound_model", lambda: Exploding())

    async def drive():
        return [raw async for raw in resident_agent.run_turn(session, "hello")]

    frames = asyncio.run(drive())

    assert len(frames) == 1
    assert frames[0].startswith("event: error")
    assert "went wrong" in frames[0]


def test_the_round_cap_says_so_instead_of_faking_a_finish(monkeypatch):
    """The old loop fell out of range(8) and sent a normal done, which looked
    exactly like a finished answer."""
    session = priya_session()
    forever = [tool_call_turn("get_my_units", {}, f"c{i}") for i in range(graph_module.MAX_TOOL_ROUNDS + 2)]

    frames = collect(session, "loop please", forever, monkeypatch)

    assert frames[-1][0] == "error"
    assert "stuck" in frames[-1][1]["message"]
    assert "done" not in [e for e, _ in frames]
