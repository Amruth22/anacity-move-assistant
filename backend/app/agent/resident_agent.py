"""The streaming agentic loop for the resident chat.

One LangGraph state machine, either provider behind it, selected by
USE_MODEL in .env. The graph in graph.py owns the control flow; this file
owns the wire format, translating the graph's two output streams into the
SSE contract the frontend has always spoken (text / tool / confirm / done /
error events). The UI doesn't know or care what runs underneath.

Token deltas arrive on LangGraph's "messages" stream. The tool and confirm
events are written by the tools node itself onto the "custom" stream, which
is what keeps a tool announcement ahead of the work it announces.
"""

import json

from langchain_core.messages import HumanMessage
from langgraph.errors import GraphRecursionError

from ..sessions import ChatSession
from ..store import store
from .graph import AGENT_GRAPH, MAX_TOOL_ROUNDS, RECURSION_LIMIT
from .history import to_messages, trim
from .prompts import resident_system_prompt


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _text_of(chunk) -> str:
    """The visible text in a model chunk.

    Content is a plain string on some providers and a list of blocks on
    others. Thinking and reasoning blocks live in that same list and must
    never reach the browser, so this reads text blocks only.
    """
    content = getattr(chunk, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)
    return ""


async def run_turn(session: ChatSession, user_text: str):
    """Async generator yielding SSE frames for one user message."""
    resident = store.resident(session.resident_id)
    community = store.community(session.community_id)
    unit = store.unit(resident["unit_id"])
    system = resident_system_prompt(resident, unit["label"] if unit else resident["unit_id"], community)

    state = {
        "messages": to_messages(session.messages) + [HumanMessage(user_text)],
        "system": system,
        "resident": resident,
        "community": community,
        "session": session,
    }

    final = None
    try:
        async for mode, chunk in AGENT_GRAPH.astream(
            state,
            stream_mode=["values", "messages", "custom"],
            config={"recursion_limit": RECURSION_LIMIT},
        ):
            if mode == "values":
                final = chunk
            elif mode == "messages":
                message, meta = chunk
                if meta.get("langgraph_node") == "agent":
                    delta = _text_of(message)
                    if delta:
                        yield _sse("text", {"delta": delta})
            elif mode == "custom":
                yield _sse(chunk["event"], chunk["payload"])
    except GraphRecursionError:
        # the model kept reaching for tools past the cap. The old loop fell
        # out of its for-range and sent a normal done, which looked exactly
        # like a finished answer. Say what happened instead.
        _save(session, final)
        yield _sse("error", {
            "message": f"I got stuck working on that (more than {MAX_TOOL_ROUNDS} steps). Could you rephrase it?",
        })
        return
    except Exception as e:  # surface API failures as a chat error, not a broken stream
        yield _sse("error", {"message": f"Something went wrong talking to the assistant ({type(e).__name__}). Please try again."})
        return

    _save(session, final)
    yield _sse("done", {})


def _save(session: ChatSession, final):
    """Write the turn back to the session, trimmed."""
    if final:
        session.messages = trim(final["messages"])
