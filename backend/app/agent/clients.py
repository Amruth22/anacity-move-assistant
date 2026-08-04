"""Provider SDK clients, built lazily.

Only the provider selected by USE_MODEL is ever constructed, so a box
configured for one provider doesn't need the other's API key in its .env.
"""

from functools import lru_cache


@lru_cache(maxsize=1)
def anthropic_client():
    from anthropic import AsyncAnthropic

    from ..config import ANTHROPIC_API_KEY

    return AsyncAnthropic(api_key=ANTHROPIC_API_KEY or None)


@lru_cache(maxsize=1)
def openai_client():
    from openai import AsyncOpenAI

    from ..config import OPENAI_API_KEY

    return AsyncOpenAI(api_key=OPENAI_API_KEY or None)
