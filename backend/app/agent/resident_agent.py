"""The streaming agentic loop for the resident chat.

Two interchangeable implementations of the same loop - one over the Anthropic
Messages API, one over the OpenAI Responses API - selected by USE_MODEL in
.env. Both speak the same SSE contract to the frontend (text / tool / done /
error events), so the UI doesn't know or care which provider is behind it.

The shape is identical either way: stream text deltas out as SSE, and when
the model asks for tools, run them all, hand back the results, and go around
again until it stops asking. Capped at 8 rounds per user turn - in practice
an intake turn uses 2-3.
"""

import json

from ..config import ANTHROPIC_MODEL, OPENAI_MODEL, USE_MODEL
from ..sessions import ChatSession
from ..store import store
from .clients import anthropic_client, openai_client
from .prompts import resident_system_prompt
from .tools import OPENAI_TOOLS, TOOL_LABELS, TOOLS, execute_tool, serialize_result

MAX_TOOL_ROUNDS = 8
MAX_OUTPUT_TOKENS = 6000


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def run_turn(session: ChatSession, user_text: str):
    """Async generator yielding SSE frames for one user message."""
    resident = store.resident(session.resident_id)
    community = store.community(session.community_id)
    unit = store.unit(resident["unit_id"])
    system = resident_system_prompt(resident, unit["label"] if unit else resident["unit_id"], community)

    session.messages.append({"role": "user", "content": user_text})
    turn = _anthropic_turn if USE_MODEL == "anthropic" else _openai_turn

    try:
        async for frame in turn(session, system, resident, community):
            yield frame
    except Exception as e:  # surface API failures as a chat error, not a broken stream
        yield _sse("error", {"message": f"Something went wrong talking to the assistant ({type(e).__name__}). Please try again."})


async def _anthropic_turn(session: ChatSession, system: str, resident: dict, community: dict):
    for _ in range(MAX_TOOL_ROUNDS):
        async with anthropic_client().messages.stream(
            model=ANTHROPIC_MODEL,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=system,
            tools=TOOLS,
            messages=session.messages,
        ) as stream:
            async for event in stream:
                if event.type == "content_block_delta" and event.delta.type == "text_delta":
                    yield _sse("text", {"delta": event.delta.text})
            response = await stream.get_final_message()

        # keep the full content (thinking blocks included) so the next
        # round replays cleanly; exclude_none strips response-only fields
        # like text.parsed_output that the API rejects on replay
        session.messages.append({
            "role": "assistant",
            "content": [block.model_dump(exclude_none=True) for block in response.content],
        })

        if response.stop_reason != "tool_use":
            break

        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            yield _sse("tool", {
                "name": block.name,
                "label": TOOL_LABELS.get(block.name, block.name),
            })
            result = execute_tool(block.name, block.input or {}, resident, community, session)
            if result.get("staged"):
                yield _sse("confirm", {"summary": result["summary"]})
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": serialize_result(result),
                "is_error": "error" in result,
            })
        session.messages.append({"role": "user", "content": results})

    session.trim()
    yield _sse("done", {})


async def _openai_turn(session: ChatSession, system: str, resident: dict, community: dict):
    for _ in range(MAX_TOOL_ROUNDS):
        stream = await openai_client().responses.create(
            model=OPENAI_MODEL,
            instructions=system,
            tools=OPENAI_TOOLS,
            input=session.messages,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            stream=True,
        )
        final = None
        async for event in stream:
            if event.type == "response.output_text.delta":
                yield _sse("text", {"delta": event.delta})
            elif event.type == "response.completed":
                final = event.response

        # replay the whole output (reasoning items included) so the next
        # round has everything the model expects to see again
        session.messages.extend(item.model_dump(exclude_none=True) for item in final.output)

        calls = [item for item in final.output if item.type == "function_call"]
        if not calls:
            break

        for call in calls:
            yield _sse("tool", {
                "name": call.name,
                "label": TOOL_LABELS.get(call.name, call.name),
            })
            try:
                args = json.loads(call.arguments) if call.arguments else {}
            except json.JSONDecodeError:
                args = {}
            result = execute_tool(call.name, args, resident, community, session)
            if result.get("staged"):
                yield _sse("confirm", {"summary": result["summary"]})
            session.messages.append({
                "type": "function_call_output",
                "call_id": call.call_id,
                "output": serialize_result(result),
            })

    session.trim()
    yield _sse("done", {})
