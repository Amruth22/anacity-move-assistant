"""Admin copilot: one structured-output call, no tool loop.

By the time an admin opens a request, the server already has everything  - 
the request, the resident, the community config. So we run the deterministic
policy checks in code, hand the model *verified* facts, and let it add the
judgment layer: summary, risks, and a recommendation. Code does truth, the
model does language and judgment.
"""

import asyncio
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from .. import policy as policy_engine
from ..config import ANTHROPIC_MODEL, OPENAI_MODEL, USE_MODEL
from ..store import store
from .clients import anthropic_client, openai_client

ASSESSMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "2-3 sentences: who, what, when, anything notable"},
        "policy_findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "rule": {"type": "string"},
                    "status": {"type": "string", "enum": ["pass", "fail", "warning"]},
                    "detail": {"type": "string"},
                },
                "required": ["rule", "status", "detail"],
                "additionalProperties": False,
            },
        },
        "missing_items": {"type": "array", "items": {"type": "string"}},
        "risk_flags": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                    "description": {"type": "string"},
                },
                "required": ["severity", "description"],
                "additionalProperties": False,
            },
        },
        "recommendation": {"type": "string", "enum": ["approve", "reject", "request_more_info"]},
        "reasoning": {"type": "string"},
        "suggested_message_to_resident": {"type": "string"},
    },
    "required": [
        "summary", "policy_findings", "missing_items", "risk_flags",
        "recommendation", "reasoning", "suggested_message_to_resident",
    ],
    "additionalProperties": False,
}

SYSTEM = """You are the admin copilot for a residential community management platform. An administrator is reviewing a move-in/move-out request and you prepare their briefing.

You receive facts that have already been verified by the platform's policy engine - do not re-derive or second-guess the automated checks; build on them. Notice-period compliance is judged as of the submission date, not the review date; do not flag a request as short-notice just because the review is happening later. Your value is judgment: what stands out, what's risky, what the admin should do, and a courteous ready-to-send note to the resident.

Be direct and specific. You recommend - the admin decides. Never phrase the recommendation as if the action has been taken.

Admins skim. Keep it tight: summary in two sentences, one short sentence per finding detail, reasoning in three or four sentences, resident message under 100 words. Skip findings that add nothing beyond the verified checks.

Put every concretely outstanding item (pending documents, pending operational tasks, unanswered required fields) into missing_items, one short entry each, taken from the verified checks. Leave it empty only when nothing is outstanding.

Never use em dashes anywhere in the briefing or the resident message. Use a comma, a colon, or a new sentence instead."""


def _build_facts(record: dict) -> dict:
    resident = store.resident(record["resident_id"])
    community = store.community(record["community_id"])
    unit = store.unit(record["unit_id"])
    pol = community["policies"][record["type"]]
    today = datetime.now(ZoneInfo(community.get("timezone", "Asia/Kolkata"))).date()

    # notice compliance is judged as of the day the resident filed - a request
    # that was valid then doesn't become a violation just because it sat in
    # the queue while moving day approached
    submitted_on = record.get("submitted_on") or (
        record["timeline"][0]["ts"][:10] if record["timeline"] else today.isoformat()
    )
    verdict = policy_engine.validate_move(
        pol, record["requested_date"], record.get("time_window"),
        datetime.strptime(submitted_on, "%Y-%m-%d").date(),
    )
    pending_docs = [c["name"] for c in record["checklist"]
                    if c.get("kind", "document") == "document" and not c["done"]]
    pending_tasks = [c["name"] for c in record["checklist"]
                     if c.get("kind") == "task" and not c["done"]]
    missing_fields = policy_engine.missing_custom_fields(pol, record.get("custom_fields", {}))

    elevator_conflicts = []
    if (pol.get("elevator_booking") or {}).get("required"):
        elevator_conflicts = [
            {"request_id": r["id"], "time_window": r.get("time_window")}
            for r in store.approved_moves_overlapping(
                community["id"], record["requested_date"],
                record.get("time_window"), exclude_id=record["id"],
            )
        ]

    return {
        "request": {
            "id": record["id"],
            "type": record["type"],
            "requested_date": record["requested_date"],
            "time_window": record["time_window"],
            "status": record["status"],
            "notes": record["notes"],
            "custom_field_answers": record["custom_fields"],
            "timeline": record["timeline"],
        },
        "resident": {"name": resident["name"], "tenancy": resident["tenancy"], "unit": unit["label"]},
        "community": {"name": community["name"], "policy_for_this_type": pol},
        "verified_checks": {
            "date_validation": verdict,
            "date_validation_note": f"Validated as of the submission date ({submitted_on}), "
                                    "which is how notice compliance is judged.",
            "pending_documents": pending_docs,
            "pending_operational_tasks": pending_tasks,
            "missing_required_fields": missing_fields,
            "elevator_slot_conflicts_with_approved_moves": elevator_conflicts,
            "submitted_on": submitted_on,
            "reviewed_on": today.isoformat(),
        },
    }


async def _run_assessment(record: dict) -> dict:
    facts = _build_facts(record)
    prompt = "Assess this request and prepare the admin briefing.\n\n" + json.dumps(facts, ensure_ascii=False)

    # low reasoning effort on both providers: the checks are already verified
    # by code, this is a summarize-and-judge pass - deep thinking buys nothing
    if USE_MODEL == "openai":
        response = await openai_client().responses.create(
            model=OPENAI_MODEL,
            instructions=SYSTEM,
            input=[{"role": "user", "content": prompt}],
            max_output_tokens=4000,
            reasoning={"effort": "low"},
            text={
                "format": {
                    "type": "json_schema",
                    "name": "admin_briefing",
                    "schema": ASSESSMENT_SCHEMA,
                    "strict": True,
                },
            },
        )
        assessment = json.loads(response.output_text)
    else:
        response = await anthropic_client().messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=2000,
            system=SYSTEM,
            output_config={
                "effort": "low",
                "format": {"type": "json_schema", "schema": ASSESSMENT_SCHEMA},
            },
            messages=[{"role": "user", "content": prompt}],
        )
        text = next(b.text for b in response.content if b.type == "text")
        assessment = json.loads(text)

    record["copilot"] = assessment
    return assessment


# one assessment per request at a time - a second caller awaits the first
_inflight: dict[str, asyncio.Task] = {}


async def assess(req_id: str) -> dict:
    record = store.requests.get(req_id)
    if record is None:
        raise KeyError(req_id)
    if record["copilot"]:
        return record["copilot"]

    task = _inflight.get(req_id)
    if task is None:
        task = asyncio.create_task(_run_assessment(record))
        _inflight[req_id] = task
        task.add_done_callback(lambda _: _inflight.pop(req_id, None))
    # shield: if this caller disconnects, the shared task keeps running
    return await asyncio.shield(task)
