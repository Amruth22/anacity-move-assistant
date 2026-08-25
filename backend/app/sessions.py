"""Chat session state, in process memory.

One session per resident conversation. Holds the message history the graph
reads and writes back, so multi-turn context and prompt caching both work.
The confirm and decline endpoints append plain role dicts here too, without
needing to know how the graph represents a turn. Trimming lives with the
graph, in agent/history.py.

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
        # LangChain messages, plus the occasional role dict from the endpoints
        self.messages: list = []
        self.created_at = datetime.now()
        self.last_request_id: str | None = None
        # a fully-validated request waiting for the resident to tap Confirm.
        # only the confirm endpoint - a human click - turns this into a request.
        self.pending_draft: dict | None = None


_sessions: dict[str, ChatSession] = {}


def create_session(resident_id: str, community_id: str) -> ChatSession:
    session = ChatSession(resident_id, community_id)
    _sessions[session.id] = session
    return session


def get_session(session_id: str) -> ChatSession | None:
    return _sessions.get(session_id)
