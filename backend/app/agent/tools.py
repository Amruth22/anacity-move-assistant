"""Tool definitions and executors for the resident-facing agent.

The trust boundary lives here: every executor receives the resident and
community from the *server-side session*, never from model arguments. The
model can only supply what the resident typed (dates, unit, answers), so a
prompt-injected "show me the other tower's requests" has no lever to pull.
"""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from .. import policy as policy_engine
from ..store import store

TOOLS = [
    {
        "name": "get_community_policy",
        "description": (
            "Fetch this community's actual move policy. Always call this before "
            "stating any rule, deadline, deposit or document requirement - never "
            "answer policy questions from memory."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "enum": ["move_in", "move_out", "all"],
                    "description": "Which policy to fetch",
                }
            },
            "required": ["topic"],
        },
    },
    {
        "name": "get_my_units",
        "description": "The unit(s) registered to this resident, with tenancy type (owner or tenant).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "validate_move_request",
        "description": (
            "Check a proposed move date and time window against community policy: "
            "notice period, allowed days, hours, blackout dates, duplicates. "
            "Returns all violations plus the earliest date that would pass. "
            "Call this before creating a request, and whenever the resident "
            "proposes or changes a date. Do not compute date rules yourself."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "request_type": {"type": "string", "enum": ["move_in", "move_out"]},
                "unit_id": {"type": "string"},
                "requested_date": {"type": "string", "description": "YYYY-MM-DD"},
                "time_window": {"type": "string", "description": "HH:MM-HH:MM, optional"},
            },
            "required": ["request_type", "unit_id", "requested_date"],
        },
    },
    {
        "name": "get_required_checklist",
        "description": (
            "Documents, deposit and extra details this specific resident must "
            "prepare for a move, filtered by their tenancy (owner vs tenant)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "request_type": {"type": "string", "enum": ["move_in", "move_out"]},
            },
            "required": ["request_type"],
        },
    },
    {
        "name": "create_move_request",
        "description": (
            "Stage the move request for the resident's final confirmation. "
            "Validation runs server-side, so an invalid date is rejected here "
            "too. This does NOT create the request - it shows the resident a "
            "confirmation card in the app, and only their tap on Confirm files "
            "it. After calling this, tell the resident to review the card and "
            "tap Confirm. Never claim the request exists yet."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "request_type": {"type": "string", "enum": ["move_in", "move_out"]},
                "unit_id": {"type": "string"},
                "requested_date": {"type": "string", "description": "YYYY-MM-DD"},
                "time_window": {"type": "string", "description": "HH:MM-HH:MM"},
                "custom_field_answers": {
                    "type": "object",
                    "description": "Answers to the community's custom fields, keyed by field key",
                },
                "notes": {"type": "string", "description": "Anything the admin should know"},
            },
            "required": ["request_type", "unit_id", "requested_date", "time_window"],
        },
    },
    {
        "name": "update_move_request",
        "description": (
            "Change or reply to one of the resident's own open requests: a new "
            "date or time window (re-validated against policy), updated answers "
            "to the community's fields, or a text reply for the admin. If the "
            "admin had asked for more information (status needs_info), any "
            "update or reply sends the request back to them as submitted. "
            "Confirm the change with the resident before calling this."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "request_id": {"type": "string"},
                "requested_date": {"type": "string", "description": "New date YYYY-MM-DD, if changing"},
                "time_window": {"type": "string", "description": "New window HH:MM-HH:MM, if changing"},
                "custom_field_answers": {
                    "type": "object",
                    "description": "Updated answers, keyed by field key - merged over existing ones",
                },
                "message": {
                    "type": "string",
                    "description": "A reply from the resident that the admin should read",
                },
                "notes": {"type": "string", "description": "Replacement for the request notes"},
            },
            "required": ["request_id"],
        },
    },
    {
        "name": "cancel_move_request",
        "description": (
            "Withdraw one of the resident's own requests (allowed while it is "
            "submitted, needs_info or approved). Ask the resident to confirm "
            "they really want to cancel before calling this."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "request_id": {"type": "string"},
            },
            "required": ["request_id"],
        },
    },
    {
        "name": "get_my_requests",
        "description": (
            "This resident's move requests with status, timeline and pending "
            "checklist items. Use for any 'what's the status' style question."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "request_id": {"type": "string", "description": "Optional: one specific request"},
            },
        },
    },
]

# same tools in the OpenAI Responses API shape (flat function entries)
OPENAI_TOOLS = [
    {
        "type": "function",
        "name": t["name"],
        "description": t["description"],
        "parameters": t["input_schema"],
    }
    for t in TOOLS
]

# short labels the UI shows while a tool runs
TOOL_LABELS = {
    "get_community_policy": "Checking community policy",
    "get_my_units": "Looking up your unit",
    "validate_move_request": "Validating the date against policy",
    "get_required_checklist": "Preparing your checklist",
    "create_move_request": "Preparing your request for confirmation",
    "update_move_request": "Updating your request",
    "cancel_move_request": "Cancelling your request",
    "get_my_requests": "Fetching your requests",
}


def _today(community: dict):
    return datetime.now(ZoneInfo(community.get("timezone", "Asia/Kolkata"))).date()


def _check_unit(resident: dict, unit_id: str):
    """The only unit a resident can act on is their own."""
    if unit_id != resident["unit_id"]:
        return {"error": f"Unit {unit_id} is not registered to you. Your unit is {resident['unit_id']}."}
    return None


def _own_request(resident: dict, request_id: str):
    """Fetch a request only if it belongs to this resident."""
    record = store.requests.get(request_id)
    if record is None or record["resident_id"] != resident["id"]:
        return None, {"error": f"No request {request_id} found for you."}
    return record, None


def _elevator_conflicts(community: dict, pol: dict, on_date: str,
                        window: str | None, exclude_id: str | None = None) -> list[dict]:
    """When the community has one bookable service elevator, two approved moves
    can't share a slot. Returns the clashing approved requests, if any."""
    elevator = pol.get("elevator_booking") or {}
    if not elevator.get("required"):
        return []
    return [
        {"request_id": r["id"], "date": r["requested_date"], "time_window": r.get("time_window")}
        for r in store.approved_moves_overlapping(community["id"], on_date, window, exclude_id)
    ]


def execute_tool(name: str, args: dict, resident: dict, community: dict, session=None) -> dict:
    """Dispatch a tool call. Always returns a JSON-serializable dict; errors
    come back as {'error': ...} so the model can recover conversationally.
    The session carries the staging area for create_move_request."""

    if name == "get_community_policy":
        topic = args.get("topic", "all")
        policies = community["policies"]
        if topic == "all":
            return {"community": community["name"], "policies": policies}
        return {"community": community["name"], "policy": policies.get(topic)}

    if name == "get_my_units":
        unit = store.unit(resident["unit_id"])
        return {
            "units": [{
                "unit_id": resident["unit_id"],
                "label": unit["label"] if unit else resident["unit_id"],
                "tenancy": resident["tenancy"],
            }]
        }

    if name == "validate_move_request":
        err = _check_unit(resident, args["unit_id"])
        if err:
            return err
        pol = community["policies"].get(args["request_type"])
        if pol is None:
            return {"error": f"Unknown request type {args['request_type']}"}
        duplicate = store.open_request_for_unit(args["unit_id"], args["request_type"]) is not None
        verdict = policy_engine.validate_move(
            pol,
            args["requested_date"],
            args.get("time_window"),
            _today(community),
            open_request_exists=duplicate,
        )
        conflicts = _elevator_conflicts(community, pol, args["requested_date"], args.get("time_window"))
        if conflicts:
            verdict["valid"] = False
            verdict["violations"].append({
                "rule": "elevator_conflict",
                "message": "The service elevator is already reserved for another approved move "
                           f"in that window ({conflicts[0]['date']} {conflicts[0]['time_window']}). "
                           "A different time window or day is needed.",
            })
        return verdict

    if name == "get_required_checklist":
        pol = community["policies"].get(args["request_type"])
        if pol is None:
            return {"error": f"Unknown request type {args['request_type']}"}
        return policy_engine.build_checklist(pol, resident["tenancy"])

    if name == "create_move_request":
        err = _check_unit(resident, args["unit_id"])
        if err:
            return err
        pol = community["policies"].get(args["request_type"])
        if pol is None:
            return {"error": f"Unknown request type {args['request_type']}"}

        duplicate = store.open_request_for_unit(args["unit_id"], args["request_type"]) is not None
        verdict = policy_engine.validate_move(
            pol, args["requested_date"], args.get("time_window"),
            _today(community), open_request_exists=duplicate,
        )
        conflicts = _elevator_conflicts(community, pol, args["requested_date"], args.get("time_window"))
        if conflicts:
            verdict["valid"] = False
            verdict["violations"].append({
                "rule": "elevator_conflict",
                "message": "The service elevator is already reserved for another approved move in that window.",
            })
        if not verdict["valid"]:
            return {"error": "Validation failed, request not staged.", "violations": verdict["violations"],
                    "earliest_valid_date": verdict["earliest_valid_date"]}

        answers = args.get("custom_field_answers") or {}
        missing = policy_engine.missing_custom_fields(pol, answers)
        if missing:
            return {"error": "Some required details are missing.", "missing_fields": missing}

        if session is None:
            return {"error": "No active session to stage the request in."}

        plan = policy_engine.build_checklist(pol, resident["tenancy"])
        checklist = (
            [{"id": d["id"], "name": d["name"], "kind": "document", "done": False, "file": None}
             for d in plan["documents"]]
            + [{"id": t["id"], "name": t["name"], "kind": "task", "done": False, "file": None}
               for t in plan["tasks"]]
        )
        # everything is validated - but the model doesn't get to file it.
        # the draft waits for the resident's tap on the confirmation card.
        session.pending_draft = {
            "req_type": args["request_type"],
            "unit_id": args["unit_id"],
            "requested_date": args["requested_date"],
            "time_window": args["time_window"],
            "checklist": checklist,
            "custom_fields": answers,
            "notes": args.get("notes", ""),
        }
        unit = store.unit(args["unit_id"])
        return {
            "staged": True,
            "summary": {
                "type": args["request_type"],
                "unit": unit["label"] if unit else args["unit_id"],
                "requested_date": args["requested_date"],
                "time_window": args["time_window"],
                "documents": [d["name"] for d in plan["documents"]],
                "tasks": [t["name"] for t in plan["tasks"]],
                "deposit": pol.get("deposit"),
            },
            "next_step": "The resident sees a confirmation card in the app. "
                         "Only their tap on Confirm files the request - tell them to review it.",
        }

    if name == "update_move_request":
        record, err = _own_request(resident, args["request_id"])
        if err:
            return err
        pol = community["policies"].get(record["type"])
        new_date = args.get("requested_date")
        new_window = args.get("time_window")
        if new_date or new_window:
            check_date = new_date or record["requested_date"]
            check_window = new_window or record.get("time_window")
            # picking a NEW date restarts the notice clock from today. but a
            # window-only change keeps the original date, whose notice was
            # already accepted at submission - judge it from that date, or an
            # otherwise-valid request would rot as moving day approaches
            if new_date:
                base_day = _today(community)
            else:
                submitted_on = record.get("submitted_on") or record["timeline"][0]["ts"][:10]
                base_day = datetime.strptime(submitted_on, "%Y-%m-%d").date()
            verdict = policy_engine.validate_move(pol, check_date, check_window, base_day)
            conflicts = _elevator_conflicts(community, pol, check_date, check_window, exclude_id=record["id"])
            if conflicts:
                verdict["valid"] = False
                verdict["violations"].append({
                    "rule": "elevator_conflict",
                    "message": "The service elevator is already reserved for another approved move in that window.",
                })
            if not verdict["valid"]:
                return {"error": "The new date/window doesn't pass policy, nothing changed.",
                        "violations": verdict["violations"],
                        "earliest_valid_date": verdict["earliest_valid_date"]}
        answers = args.get("custom_field_answers") or {}
        if answers:
            merged = {**record["custom_fields"], **answers}
            missing = policy_engine.missing_custom_fields(pol, merged)
            if missing:
                return {"error": "Those answers leave required details missing.", "missing_fields": missing}
        try:
            record = store.update_request(
                record["id"],
                requested_date=new_date,
                time_window=new_window,
                custom_fields=answers or None,
                notes=args.get("notes"),
                message=args.get("message", ""),
                actor_name=resident["name"],
            )
        except ValueError as e:
            return {"error": str(e)}
        return {"request_id": record["id"], "status": record["status"],
                "requested_date": record["requested_date"], "time_window": record["time_window"]}

    if name == "cancel_move_request":
        record, err = _own_request(resident, args["request_id"])
        if err:
            return err
        try:
            record = store.cancel_request(record["id"], resident["name"])
        except ValueError as e:
            return {"error": str(e)}
        return {"request_id": record["id"], "status": record["status"]}

    if name == "get_my_requests":
        records = store.requests_for_resident(resident["id"])
        if args.get("request_id"):
            records = [r for r in records if r["id"] == args["request_id"]]
        def item_state(c):
            if c.get("kind", "document") == "task":
                return "done" if c.get("done") else "pending (the admin desk handles this)"
            if c.get("done"):
                return "verified by admin"
            if c.get("file"):
                return f"uploaded ({c['file']['filename']}), awaiting admin review"
            return "not uploaded yet"

        return {
            "requests": [{
                "id": r["id"],
                "type": r["type"],
                "requested_date": r["requested_date"],
                "time_window": r["time_window"],
                "status": r["status"],
                "checklist": [
                    {"name": c["name"], "kind": c.get("kind", "document"), "state": item_state(c)}
                    for c in r["checklist"]
                ],
                "timeline": r["timeline"],
            } for r in records]
        }

    return {"error": f"Unknown tool {name}"}


def serialize_result(result: dict) -> str:
    return json.dumps(result, ensure_ascii=False)
