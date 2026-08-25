"""Conversation history for the graph.

The session stores LangChain messages, but the confirm and decline endpoints
append plain {"role": "user", "content": "..."} dicts without knowing that -
they just want to tell the model what the human did. convert_to_messages
accepts both in one list, so those endpoints stay untouched.

trim() keeps the same rule the hand-written loop used: cut at a real user
turn, never between a tool call and its result.
"""

from langchain_core.messages import BaseMessage, HumanMessage, convert_to_messages

KEEP = 40


def to_messages(raw: list) -> list[BaseMessage]:
    """Normalise a session history that may mix message objects and role dicts."""
    return list(convert_to_messages(raw))


def _is_user_turn(msg: BaseMessage) -> bool:
    """A real user turn, not a tool result riding in a user-role message."""
    return isinstance(msg, HumanMessage) and isinstance(msg.content, str)


def trim(messages: list[BaseMessage], keep: int = KEEP) -> list[BaseMessage]:
    """Keep the tail of a long conversation, cutting at a user-text boundary."""
    if len(messages) <= keep:
        return list(messages)
    cut = len(messages) - keep
    while cut < len(messages):
        if _is_user_turn(messages[cut]):
            break
        cut += 1
    return list(messages[cut:])
