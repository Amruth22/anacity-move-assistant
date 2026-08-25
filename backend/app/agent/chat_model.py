"""The chat model the graph runs on, built lazily.

One graph, two providers. Everything above this file is provider-agnostic:
the graph, the tools node and the SSE emitter never learn which model is
answering. Swapping provider is USE_MODEL in .env and a restart, same as
before, except now only this factory changes shape instead of a whole
second copy of the loop.

Only the configured provider's package is imported, so a box set up for one
provider doesn't need the other's key or its SDK loaded.
"""

from functools import lru_cache

from .tools import TOOLS

MAX_OUTPUT_TOKENS = 6000

# LangChain re-renders these per provider, so the eight schemas in tools.py
# stay the single source of truth for both.
LC_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": t["name"],
            "description": t["description"],
            "parameters": t["input_schema"],
        },
    }
    for t in TOOLS
]


@lru_cache(maxsize=1)
def chat_model():
    from ..config import (
        ANTHROPIC_API_KEY,
        ANTHROPIC_MODEL,
        OPENAI_API_KEY,
        OPENAI_MODEL,
        USE_MODEL,
    )

    if USE_MODEL == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=ANTHROPIC_MODEL,
            api_key=ANTHROPIC_API_KEY or None,
            max_tokens=MAX_OUTPUT_TOKENS,
            # adaptive thinking: the model decides when the question is worth
            # thinking about. Unrecognised kwargs pass straight through to
            # messages.create, which is how this survives the LangChain layer.
            thinking={"type": "adaptive"},
        )

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=OPENAI_MODEL,
        api_key=OPENAI_API_KEY or None,
        use_responses_api=True,
        max_tokens=MAX_OUTPUT_TOKENS,
    )


@lru_cache(maxsize=1)
def bound_model():
    """The model with the eight resident tools attached."""
    return chat_model().bind_tools(LC_TOOLS)
