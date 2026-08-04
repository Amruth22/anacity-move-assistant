from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ..agent.resident_agent import run_turn
from ..models import ChatBody, ChatSessionBody, ConfirmBody
from ..sessions import create_session, get_session
from ..store import store

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/session")
def new_session(body: ChatSessionBody):
    resident = store.resident(body.resident_id)
    if resident is None:
        raise HTTPException(404, "Unknown resident")
    session = create_session(resident["id"], resident["community_id"])
    return {"session_id": session.id}


@router.post("")
async def chat(body: ChatBody):
    session = get_session(body.session_id)
    if session is None:
        raise HTTPException(404, "Unknown or expired session. Start a new one.")
    if not body.message.strip():
        raise HTTPException(422, "Empty message")

    return StreamingResponse(
        run_turn(session, body.message),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/confirm")
def confirm_request(body: ConfirmBody):
    """The autonomy boundary, made physical: the agent can only stage a
    request. This endpoint - reached by the resident tapping Confirm in the
    app, never by the model - is the only code path that files it."""
    session = get_session(body.session_id)
    if session is None:
        raise HTTPException(404, "Unknown or expired session")
    draft = session.pending_draft
    if draft is None:
        raise HTTPException(409, "Nothing is waiting for confirmation")
    session.pending_draft = None  # single-use, so a double click can't file twice

    # the world may have moved since the draft was staged - another session
    # can have filed a request or taken the elevator slot. re-check both here,
    # in the same single-threaded step that files, so no gap remains.
    resident = store.resident(session.resident_id)
    community = store.community(session.community_id)
    pol = community["policies"][draft["req_type"]]
    conflict = None
    if store.open_request_for_unit(draft["unit_id"], draft["req_type"]):
        conflict = "An open request for this unit already exists. It may have been filed from another session."
    elif (pol.get("elevator_booking") or {}).get("required") and store.approved_moves_overlapping(
        community["id"], draft["requested_date"], draft["time_window"]
    ):
        conflict = "The service elevator was booked for that window while this draft was waiting. Ask the assistant for a different slot."
    if conflict:
        session.messages.append({
            "role": "user",
            "content": f"[app note] The confirmation failed: {conflict}",
        })
        raise HTTPException(409, conflict)

    record = store.create_request(
        req_type=draft["req_type"],
        resident=resident,
        unit_id=draft["unit_id"],
        requested_date=draft["requested_date"],
        time_window=draft["time_window"],
        checklist=draft["checklist"],
        custom_fields=draft["custom_fields"],
        notes=draft["notes"],
    )
    session.last_request_id = record["id"]
    # let the conversation know without a model round-trip
    session.messages.append({
        "role": "user",
        "content": f"[app note] The resident tapped Confirm. Request {record['id']} is now filed.",
    })
    return {"request_id": record["id"], "status": record["status"]}


@router.post("/decline")
def decline_request(body: ConfirmBody):
    session = get_session(body.session_id)
    if session is None:
        raise HTTPException(404, "Unknown or expired session")
    session.pending_draft = None
    session.messages.append({
        "role": "user",
        "content": "[app note] The resident dismissed the confirmation card without filing the request.",
    })
    return {"declined": True}
