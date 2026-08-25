"""The resident agent as a LangGraph state machine.

Two nodes and one decision:

    agent  --tool calls?--> tools --> agent
      |
      +--no--> END

That is the whole loop. What used to be a hand-written for-range(8) with
provider-specific stream handling on both sides of it is now a graph, and
the round cap is a recursion limit the runtime enforces.

The tools node is written by hand rather than using the prebuilt ToolNode on
purpose. The trust boundary is that the resident and the community come from
the server session and never from model arguments, so the node reads them
from graph state and passes them into the same executor the tests drive
directly.
"""

from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage, SystemMessage, ToolMessage
from langgraph.config import get_stream_writer
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from ..sessions import ChatSession
from .chat_model import bound_model
from .tools import TOOL_LABELS, execute_tool, serialize_result

MAX_TOOL_ROUNDS = 8
# one agent node and one tools node per round, plus the closing agent turn
RECURSION_LIMIT = MAX_TOOL_ROUNDS * 2 + 1


class ChatState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    system: str
    resident: dict
    community: dict
    session: ChatSession


async def call_model(state: ChatState) -> dict:
    """Ask the model what to do next, streaming its tokens as it writes."""
    messages = [SystemMessage(state["system"])] + list(state["messages"])
    reply = None
    async for chunk in bound_model().astream(messages):
        reply = chunk if reply is None else reply + chunk
    return {"messages": [reply]}


def run_tools(state: ChatState) -> dict:
    """Run every tool the model asked for, in order, announcing each one first."""
    writer = get_stream_writer()
    results = []

    for call in state["messages"][-1].tool_calls:
        name = call["name"]
        writer({"event": "tool", "payload": {"name": name, "label": TOOL_LABELS.get(name, name)}})

        # resident and community come from the session, never from the model
        result = execute_tool(name, call["args"] or {}, state["resident"], state["community"], state["session"])

        # a staged request is the autonomy boundary: the model has prepared
        # everything, and the card it triggers is the human's to tap
        if result.get("staged"):
            writer({"event": "confirm", "payload": {"summary": result["summary"]}})

        results.append(ToolMessage(
            content=serialize_result(result),
            tool_call_id=call["id"],
            name=name,
            status="error" if "error" in result else "success",
        ))

    return {"messages": results}


def should_continue(state: ChatState) -> str:
    last = state["messages"][-1]
    return "tools" if getattr(last, "tool_calls", None) else END


def build_graph():
    graph = StateGraph(ChatState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", run_tools)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")
    # no checkpointer: the conversation lives in the ChatSession, and the
    # human-in-the-loop pause is an HTTP round trip, not a graph interrupt
    return graph.compile()


AGENT_GRAPH = build_graph()
