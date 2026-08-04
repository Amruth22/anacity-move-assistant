from datetime import date

from app.policy import build_checklist, earliest_valid_date, missing_custom_fields, validate_move
from app.store import Store

# A Tuesday. Keeps weekday assertions readable below.
TODAY = date(2026, 8, 4)

STRICT = {
    "notice_days": 7,
    "allowed_days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
    "hours": {"start": "09:00", "end": "18:00"},
    "blackout_dates": ["2026-08-15", "2026-08-11"],
    "deposit": {"amount": 10000, "currency": "INR", "refundable": True},
    "elevator_booking": {"required": True, "note": "Service elevator only"},
    "documents": [
        {"id": "noc", "name": "Society NOC", "required_for": ["owner", "tenant"]},
        {"id": "rental", "name": "Rental agreement", "required_for": ["tenant"]},
    ],
    "custom_fields": [
        {"key": "mover_company", "label": "Moving company", "type": "text", "required": True},
        {"key": "truck_size", "label": "Truck size", "type": "text", "required": False},
    ],
}


def rules(result):
    return {v["rule"] for v in result["violations"]}


def test_exact_notice_boundary_is_valid():
    # 7 days from Tue Aug 4 is Tue Aug 11 - but that's a blackout, so use a
    # policy without blackouts to isolate the notice rule.
    policy = {**STRICT, "blackout_dates": []}
    result = validate_move(policy, "2026-08-11", "10:00-12:00", TODAY)
    assert result["valid"], result["violations"]


def test_one_day_short_of_notice_fails():
    result = validate_move(STRICT, "2026-08-10", "10:00-12:00", TODAY)
    assert "notice_period" in rules(result)


def test_weekend_rejected_in_strict_community():
    # Aug 16 2026 is a Sunday, comfortably past notice
    result = validate_move(STRICT, "2026-08-16", "10:00-12:00", TODAY)
    assert "allowed_days" in rules(result)


def test_blackout_date_rejected():
    result = validate_move(STRICT, "2026-08-15", "10:00-12:00", TODAY)
    assert "blackout_date" in rules(result)


def test_window_outside_hours_rejected():
    result = validate_move(STRICT, "2026-08-12", "07:00-09:00", TODAY)
    assert "hours" in rules(result)


def test_past_date_rejected():
    result = validate_move(STRICT, "2026-08-01", "10:00-12:00", TODAY)
    assert "past_date" in rules(result)


def test_garbage_date_rejected_cleanly():
    result = validate_move(STRICT, "next tuesday", None, TODAY)
    assert not result["valid"]
    assert "date_format" in rules(result)


def test_duplicate_open_request_flagged():
    result = validate_move(STRICT, "2026-08-12", "10:00-12:00", TODAY, open_request_exists=True)
    assert "duplicate_request" in rules(result)


def test_multiple_violations_reported_together():
    # Sunday AND short notice AND bad hours - the agent should get all three
    result = validate_move(STRICT, "2026-08-09", "06:00-08:00", TODAY)
    assert {"notice_period", "allowed_days", "hours"} <= rules(result)


def test_earliest_valid_date_skips_weekend_and_blackout():
    # notice lands on Tue Aug 11 (blackout) -> Wed Aug 12
    assert earliest_valid_date(STRICT, TODAY) == "2026-08-12"


def test_checklist_differs_by_tenancy():
    tenant = build_checklist(STRICT, "tenant")
    owner = build_checklist(STRICT, "owner")
    tenant_docs = {d["id"] for d in tenant["documents"]}
    owner_docs = {d["id"] for d in owner["documents"]}
    assert "rental" in tenant_docs
    assert "rental" not in owner_docs
    assert "noc" in owner_docs


def test_missing_custom_fields_only_flags_required_unanswered():
    assert missing_custom_fields(STRICT, {}) == ["Moving company"]
    assert missing_custom_fields(STRICT, {"mover_company": "SafeShift"}) == []
    # boolean False must count as answered
    policy = {"custom_fields": [{"key": "pets", "label": "Pets?", "type": "boolean", "required": True}]}
    assert missing_custom_fields(policy, {"pets": False}) == []


# --- store behaviour --------------------------------------------------------

def make_store():
    s = Store()
    s.seed()
    return s


def test_seed_loads_two_contrasting_communities():
    s = make_store()
    assert len(s.communities) == 2
    strict = s.community("lakeview-heights")["policies"]["move_in"]
    relaxed = s.community("palm-meadows")["policies"]["move_in"]
    assert strict["notice_days"] > relaxed["notice_days"]
    assert strict["deposit"] and not relaxed["deposit"]


def test_cannot_approve_a_rejected_request():
    s = make_store()
    import pytest
    with pytest.raises(ValueError):
        s.apply_action("req-1005", "approve", "changed my mind")


def test_approve_from_needs_info_is_allowed():
    s = make_store()
    record = s.apply_action("req-1002", "approve", "dues cleared over the counter")
    assert record["status"] == "approved"
    assert record["timeline"][-1]["event"] == "approved"


def test_admin_action_invalidates_cached_copilot():
    s = make_store()
    s.requests["req-1001"]["copilot"] = {"recommendation": "approve"}
    s.apply_action("req-1001", "request_info", "need the rental agreement")
    assert s.requests["req-1001"]["copilot"] is None


def test_open_request_detection():
    s = make_store()
    assert s.open_request_for_unit("u-lh-2301", "move_in") is not None   # req-1001 submitted
    assert s.open_request_for_unit("u-pm-12", "move_out") is None        # req-1004 completed
