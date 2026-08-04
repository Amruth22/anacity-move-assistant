"""Deterministic policy engine.

Everything here is pure functions over a community's config dict. The agent
never does date math or quotes rules from memory - it calls tools that call
these functions, so the answers are always grounded in the actual config.
"""

from datetime import date, datetime, timedelta

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _parse_window(window: str):
    """'10:00-12:00' -> ('10:00', '12:00'), or None if malformed."""
    try:
        start, end = window.split("-")
        datetime.strptime(start.strip(), "%H:%M")
        datetime.strptime(end.strip(), "%H:%M")
        return start.strip(), end.strip()
    except (ValueError, AttributeError):
        return None


def earliest_valid_date(policy: dict, today: date) -> str | None:
    """First date that clears the notice period, lands on an allowed weekday
    and isn't blacked out. Scans 90 days ahead, which is plenty for a demo."""
    start = today + timedelta(days=policy["notice_days"])
    blackouts = set(policy.get("blackout_dates", []))
    for offset in range(90):
        candidate = start + timedelta(days=offset)
        if WEEKDAYS[candidate.weekday()] not in policy["allowed_days"]:
            continue
        if candidate.isoformat() in blackouts:
            continue
        return candidate.isoformat()
    return None


def validate_move(
    policy: dict,
    requested_date: str,
    time_window: str | None,
    today: date,
    open_request_exists: bool = False,
) -> dict:
    """Check a proposed move against community policy. Returns every violation
    at once so the agent can explain them all in a single reply."""
    violations = []

    try:
        move_date = _parse_date(requested_date)
    except ValueError:
        return {
            "valid": False,
            "violations": [{"rule": "date_format", "message": f"'{requested_date}' is not a valid date. Use YYYY-MM-DD."}],
            "earliest_valid_date": earliest_valid_date(policy, today),
        }

    if move_date < today:
        violations.append({"rule": "past_date", "message": "The requested date is in the past."})

    notice = policy["notice_days"]
    if (move_date - today).days < notice:
        violations.append({
            "rule": "notice_period",
            "message": f"This community requires {notice} days' notice. "
                       f"The requested date is only {(move_date - today).days} day(s) away.",
        })

    weekday = WEEKDAYS[move_date.weekday()]
    if weekday not in policy["allowed_days"]:
        allowed = ", ".join(policy["allowed_days"])
        violations.append({
            "rule": "allowed_days",
            "message": f"Moves are not permitted on {weekday}. Allowed days: {allowed}.",
        })

    if requested_date in policy.get("blackout_dates", []):
        violations.append({
            "rule": "blackout_date",
            "message": f"{requested_date} is a blackout date for this community (no moves allowed).",
        })

    if time_window:
        parsed = _parse_window(time_window)
        if parsed is None:
            violations.append({
                "rule": "time_format",
                "message": f"'{time_window}' is not a valid time window. Use HH:MM-HH:MM.",
            })
        else:
            start, end = parsed
            hours = policy["hours"]
            if start < hours["start"] or end > hours["end"] or start >= end:
                violations.append({
                    "rule": "hours",
                    "message": f"Moves are allowed between {hours['start']} and {hours['end']} here. "
                               f"The window {time_window} falls outside that.",
                })

    if open_request_exists:
        violations.append({
            "rule": "duplicate_request",
            "message": "There is already an open request for this unit. Update or wait on that one instead.",
        })

    return {
        "valid": not violations,
        "violations": violations,
        "earliest_valid_date": earliest_valid_date(policy, today),
    }


def build_checklist(policy: dict, tenancy: str) -> dict:
    """What this specific resident needs to prepare - documents filtered by
    owner/tenant, operational tasks derived from the policy (deposit, elevator),
    plus any community-specific extra fields."""
    documents = [
        {"id": d["id"], "name": d["name"]}
        for d in policy.get("documents", [])
        if tenancy in d.get("required_for", [])
    ]
    return {
        "documents": documents,
        "tasks": operational_tasks(policy),
        "deposit": policy.get("deposit"),
        "elevator_booking": policy.get("elevator_booking"),
        "custom_fields": policy.get("custom_fields", []),
    }


def operational_tasks(policy: dict) -> list[dict]:
    """Non-document workflow items the request has to clear before the move  - 
    derived from the same config that drives everything else."""
    tasks = []
    deposit = policy.get("deposit")
    if deposit and deposit.get("amount"):
        tasks.append({
            "id": "deposit_payment",
            "name": f"Pay move deposit ({deposit.get('currency', 'INR')} {deposit['amount']:,})",
        })
    elevator = policy.get("elevator_booking")
    if elevator and elevator.get("required"):
        tasks.append({"id": "elevator_booking", "name": "Book the service elevator slot"})
    return tasks


def missing_custom_fields(policy: dict, answers: dict) -> list[str]:
    """Required custom fields without a usable answer. A boolean False is a
    real answer; None, absence, an empty string, or a value of the wrong type
    is not."""
    missing = []
    for field in policy.get("custom_fields", []):
        if not field.get("required"):
            continue
        value = answers.get(field["key"])
        ftype = field.get("type", "text")
        ok = (
            isinstance(value, bool) if ftype == "boolean"
            else isinstance(value, str) and value.strip() != ""
        )
        if not ok:
            missing.append(field["label"])
    return missing
