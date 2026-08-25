"""The admin briefing as a two-node graph.

    facts --> assess --> END

Deliberately not an agent. The policy checks are already settled by code
before the model is called, so there is nothing for a loop to discover: the
facts node gathers verified findings, the assess node turns them into
language and a recommendation. One round trip, no loop failure modes.

Structured output is enforced by the provider against ASSESSMENT_SCHEMA, so
the admin panel always gets the field names it renders.
"""

import json
from typing import TypedDict

from langchain_core.messages import HumanMessage, SystemMessage

from ..config import USE_MODEL
from .chat_model import chat_model


class BriefingState(TypedDict, total=False):
    record: dict
    facts: dict
    assessment: dict


def _facts_node(state: BriefingState) -> dict:
    from .copilot import _build_facts

    return {"facts": _build_facts(state["record"])}


async def _assess_node(state: BriefingState) -> dict:
    from .copilot import ASSESSMENT_SCHEMA, SYSTEM

    prompt = "Assess this request and prepare the admin briefing.\n\n" + json.dumps(state["facts"], ensure_ascii=False)
    messages = [SystemMessage(SYSTEM), HumanMessage(prompt)]

    # low reasoning effort on both providers: the checks are already verified
    # by code, this is a summarize-and-judge pass - deep thinking buys nothing
    if USE_MODEL == "anthropic":
        model = chat_model().bind(
            max_tokens=2000,
            output_config={
                "effort": "low",
                "format": {"type": "json_schema", "schema": ASSESSMENT_SCHEMA},
            },
        )
        reply = await model.ainvoke(messages)
        assessment = json.loads(reply.text if isinstance(reply.text, str) else reply.text())
    else:
        model = chat_model().bind(reasoning={"effort": "low"}).with_structured_output(
            {
                "type": "json_schema",
                "name": "admin_briefing",
                "schema": ASSESSMENT_SCHEMA,
                "strict": True,
            },
        )
        assessment = await model.ainvoke(messages)

    return {"assessment": assessment}


def build_graph():
    from langgraph.graph import END, StateGraph

    graph = StateGraph(BriefingState)
    graph.add_node("facts", _facts_node)
    graph.add_node("assess", _assess_node)
    graph.set_entry_point("facts")
    graph.add_edge("facts", "assess")
    graph.add_edge("assess", END)
    return graph.compile()


COPILOT_GRAPH = build_graph()


async def run_briefing(record: dict) -> dict:
    final = await COPILOT_GRAPH.ainvoke({"record": record})
    return final["assessment"]
