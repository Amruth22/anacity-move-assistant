"""Request/response bodies for the API. Internal records stay as plain dicts
loaded from seed JSON - the store is the single owner of that shape."""

from typing import Literal, Optional

from pydantic import BaseModel


class ChatSessionBody(BaseModel):
    resident_id: str


class ChatBody(BaseModel):
    session_id: str
    message: str


class ConfirmBody(BaseModel):
    session_id: str


class AdminActionBody(BaseModel):
    action: Literal["approve", "reject", "request_info", "complete"]
    note: Optional[str] = None
