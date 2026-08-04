from types import SimpleNamespace

import pytest

from app.agent.tools import execute_tool
from app.store import store


@pytest.fixture(autouse=True)
def fresh_store():
    # tools act on the module-level store; reseed so tests don't leak state
    store.seed()
    yield
    store.seed()


def ctx(resident_id):
    resident = store.resident(resident_id)
    community = store.community(resident["community_id"])
    return resident, community


def chat_session():
    """Stand-in for a ChatSession: the tools only touch pending_draft."""
    return SimpleNamespace(pending_draft=None)


def test_resident_cannot_touch_someone_elses_unit():
    resident, community = ctx("r-priya")
    result = execute_tool("validate_move_request", {
        "request_type": "move_in", "unit_id": "u-lh-702", "requested_date": "2026-09-01",
    }, resident, community)
    assert "error" in result
    assert "not registered to you" in result["error"]


def test_create_rejects_invalid_date_even_when_called_directly():
    # defense in depth: the model could skip validate and call create straight away
    resident, community = ctx("r-priya")
    result = execute_tool("create_move_request", {
        "request_type": "move_out",
        "unit_id": "u-lh-1204",
        "requested_date": "2026-08-05",       # way inside the 15-day notice
        "time_window": "10:00-12:00",
        "custom_field_answers": {"mover_company": "SafeShift"},
    }, resident, community)
    assert "error" in result
    assert any(v["rule"] == "notice_period" for v in result["violations"])


def test_create_rejects_missing_required_custom_field():
    resident, community = ctx("r-priya")
    result = execute_tool("create_move_request", {
        "request_type": "move_out",
        "unit_id": "u-lh-1204",
        "requested_date": "2026-08-24",       # Monday, > 15 days out
        "time_window": "10:00-12:00",
        "custom_field_answers": {},
    }, resident, community)
    assert "error" in result
    assert "Moving company name" in result["missing_fields"]


def test_create_stages_a_draft_instead_of_filing():
    # the model can't file a request - it can only stage one for the
    # resident's confirmation click
    resident, community = ctx("r-priya")
    session = chat_session()
    before = set(store.requests)
    result = execute_tool("create_move_request", {
        "request_type": "move_out",
        "unit_id": "u-lh-1204",
        "requested_date": "2026-08-24",
        "time_window": "10:00-12:00",
        "custom_field_answers": {"mover_company": "SafeShift"},
        "notes": "third floor stuff goes first",
    }, resident, community, session)
    assert result.get("staged") is True
    assert set(store.requests) == before          # nothing filed yet
    assert session.pending_draft is not None

    # tenant moving out of Lakeview needs the owner's NOC; an owner wouldn't  - 
    # and the single service elevator shows up as a trackable task
    names = {c["name"] for c in session.pending_draft["checklist"]}
    assert "Owner's NOC for vacating" in names
    kinds = {c["id"]: c["kind"] for c in session.pending_draft["checklist"]}
    assert kinds.get("elevator_booking") == "task"

    # the confirm endpoint's job: turn the draft into the request
    record = store.create_request(
        req_type=session.pending_draft["req_type"], resident=resident,
        unit_id=session.pending_draft["unit_id"],
        requested_date=session.pending_draft["requested_date"],
        time_window=session.pending_draft["time_window"],
        checklist=session.pending_draft["checklist"],
        custom_fields=session.pending_draft["custom_fields"],
        notes=session.pending_draft["notes"],
    )
    assert record["status"] == "submitted"
    assert record["submitted_on"] == record["timeline"][0]["ts"][:10]


def test_create_without_session_cannot_file_anything():
    resident, community = ctx("r-priya")
    result = execute_tool("create_move_request", {
        "request_type": "move_out", "unit_id": "u-lh-1204",
        "requested_date": "2026-08-24", "time_window": "10:00-12:00",
        "custom_field_answers": {"mover_company": "SafeShift"},
    }, resident, community)
    assert "error" in result


def test_duplicate_open_request_blocks_creation():
    resident, community = ctx("r-meera")  # already has open move_in req-1001
    result = execute_tool("create_move_request", {
        "request_type": "move_in",
        "unit_id": "u-lh-2301",
        "requested_date": "2026-08-24",
        "time_window": "10:00-12:00",
        "custom_field_answers": {"mover_company": "X Movers"},
    }, resident, community)
    assert "error" in result
    assert any(v["rule"] == "duplicate_request" for v in result["violations"])


def test_get_my_requests_only_shows_own():
    resident, community = ctx("r-meera")
    result = execute_tool("get_my_requests", {}, resident, community)
    ids = {r["id"] for r in result["requests"]}
    assert ids == {"req-1001"}


def test_policy_tool_returns_community_specific_rules():
    _, lakeview = ctx("r-priya")
    _, palms = ctx("r-sana")
    strict = execute_tool("get_community_policy", {"topic": "move_in"}, store.resident("r-priya"), lakeview)
    relaxed = execute_tool("get_community_policy", {"topic": "move_in"}, store.resident("r-sana"), palms)
    assert strict["policy"]["notice_days"] == 7
    assert relaxed["policy"]["notice_days"] == 2


def test_checklist_tool_respects_tenancy():
    resident, community = ctx("r-arjun")  # owner
    result = execute_tool("get_required_checklist", {"request_type": "move_in"}, resident, community)
    docs = {d["id"] for d in result["documents"]}
    assert "rental_agreement" not in docs
    assert "noc_society" in docs
