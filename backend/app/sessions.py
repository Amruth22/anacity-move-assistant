"""Chat session state, in process memory.

One session per resident conversation. Holds the provider-native message
history verbatim (Anthropic content blocks or OpenAI Responses items,
depending on USE_MODEL) so multi-turn context and prompt caching both work.
The provider is fixed for the life of the process, so histories never mix.
Single-worker deployment is a hard requirement while this lives in memory  - 
the systemd unit runs uvicorn with --workers 1.
"""

import uuid
from datetime import datetime


class ChatSession:
    def __init__(self, resident_id: str, community_id: str):
        self.id = str(uuid.uuid4())
        self.resident_id = resident_id
        self.community_id = community_id
        self.messages: list[dict] = []
        self.created_at = datetime.now()
        self.last_request_id: str | None = None
        # a fully-validated request waiting for the resident to tap Confirm.
        # only the confirm endpoint - a human click - turns this into a request.
        self.pending_draft: dict | None = None

    def trim(self, keep: int = 40):
        """Keep the tail of long conversations. We cut at a user-text boundary
        so we never orphan a tool result from its tool call (or an OpenAI
        reasoning item from the calls that follow it)."""
        if len(self.messages) <= keep:
            return
        cut = len(self.messages) - keep
        while cut < len(self.messages):
            msg = self.messages[cut]
            if msg.get("role") == "user" and isinstance(msg.get("content"), str):
                break
            cut += 1
        self.messages = self.messages[cut:]


_sessions: dict[str, ChatSession] = {}


def create_session(resident_id: str, community_id: str) -> ChatSession:
    session = ChatSession(resident_id, community_id)
    _sessions[session.id] = session
    return session


def get_session(session_id: str) -> ChatSession | None:
    return _sessions.get(session_id)
