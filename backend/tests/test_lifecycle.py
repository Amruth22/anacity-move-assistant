"""The request lifecycle beyond the happy path: the needs-info loop,
cancellation, duplicate rules around approved requests, operational tasks,
and the elevator-slot conflict check."""

import pytest

from app.agent.tools import execute_tool
from app.store import store


@pytest.fixture(autouse=True)
def fresh_store():
    store.seed()
    yield
    store.seed()


def ctx(resident_id):
    resident = store.resident(resident_id)
    community = store.community(resident["community_id"])
    return resident, community


# --- the needs-info loop -----------------------------------------------------

def test_resident_reply_resubmits_a_needs_info_request():
    resident, community = ctx("r-arjun")  # req-1002 is needs_info
    result = execute_tool("update_move_request", {
        "request_id": "req-1002",
        "message": "Dues are cleared, receipt attached to the certificate upload.",
    }, resident, community)
    assert result["status"] == "submitted"
    events = [t["event"] for t in store.requests["req-1002"]["timeline"]]
    assert "resident_reply" in events
    assert events[-1] == "resubmitted"


def test_admin_can_request_info_twice():
    store.apply_action("req-1002", "request_info", "One more thing - the receipt too, please.")
    assert store.requests["req-1002"]["status"] == "needs_info"


def test_update_revalidates_dates():
    resident, community = ctx("r-arjun")
    result = execute_tool("update_move_request", {
        "request_id": "req-1002",
        "requested_date": "2026-08-06",  # inside the 15-day notice
    }, resident, community)
    assert "error" in result
    assert any(v["rule"] == "notice_period" for v in result["violations"])
    # and nothing changed on the record
    assert store.requests["req-1002"]["requested_date"] == "2026-08-25"


def test_update_is_owner_only():
    resident, community = ctx("r-priya")  # req-1002 belongs to Arjun
    result = execute_tool("update_move_request", {
        "request_id": "req-1002", "message": "hello",
    }, resident, community)
    assert "error" in result


def test_cancel_withdraws_and_blocks_further_edits():
    resident, community = ctx("r-arjun")
    result = execute_tool("cancel_move_request", {"request_id": "req-1002"}, resident, community)
    assert result["status"] == "cancelled"
    again = execute_tool("update_move_request", {
        "request_id": "req-1002", "message": "wait, undo",
    }, resident, community)
    assert "error" in again


def test_completed_requests_cannot_be_cancelled():
    resident, community = ctx("r-dev")  # req-1004 is completed
    result = execute_tool("cancel_move_request", {"request_id": "req-1004"}, resident, community)
    assert "error" in result


def test_window_only_update_keeps_submission_notice():
    # filed long ago with a date that is now inside the notice window from
    # today - changing just the time window must not re-run the notice clock
    record = store.requests["req-1002"]
    record["requested_date"] = "2026-08-10"
    record["submitted_on"] = "2026-07-20"
    resident, community = ctx("r-arjun")
    result = execute_tool("update_move_request", {
        "request_id": "req-1002", "time_window": "14:00-16:00",
    }, resident, community)
    assert "error" not in result
    assert store.requests["req-1002"]["time_window"] == "14:00-16:00"

    # but a NEW date restarts the clock from today
    result = execute_tool("update_move_request", {
        "request_id": "req-1002", "requested_date": "2026-08-11",
    }, resident, community)
    assert "error" in result
    assert any(v["rule"] == "notice_period" for v in result["violations"])


# --- admin guard rails --------------------------------------------------------

def test_request_info_requires_a_note():
    with pytest.raises(ValueError):
        store.apply_action("req-1001", "request_info", "   ")


def test_reject_requires_a_note():
    with pytest.raises(ValueError):
        store.apply_action("req-1001", "reject", None)


def test_approving_over_pending_items_needs_an_override_note():
    # req-1001 still has a pending rental agreement and both tasks
    with pytest.raises(ValueError):
        store.apply_action("req-1001", "approve", "")
    record = store.apply_action("req-1001", "approve", "Agreement sighted at the desk; filing copy to follow.")
    assert record["status"] == "approved"


# --- the confirmation endpoint race ------------------------------------------

def test_second_confirmation_of_the_same_unit_is_rejected():
    from fastapi import HTTPException

    from app.models import ConfirmBody
    from app.routers.chat import confirm_request
    from app.sessions import create_session

    draft = {
        "req_type": "move_out", "unit_id": "u-lh-1204",
        "requested_date": "2026-08-24", "time_window": "10:00-12:00",
        "checklist": [], "custom_fields": {"mover_company": "SafeShift"}, "notes": "",
    }
    s1 = create_session("r-priya", "lakeview-heights")
    s2 = create_session("r-priya", "lakeview-heights")
    s1.pending_draft = dict(draft)
    s2.pending_draft = dict(draft)

    first = confirm_request(ConfirmBody(session_id=s1.id))
    assert first["request_id"].startswith("req-")
    with pytest.raises(HTTPException) as exc:
        confirm_request(ConfirmBody(session_id=s2.id))
    assert exc.value.status_code == 409
    # and the losing session's draft is gone - no retry can file it either
    assert s2.pending_draft is None


def test_confirmation_rechecks_elevator_availability():
    from fastapi import HTTPException

    from app.models import ConfirmBody
    from app.routers.chat import confirm_request
    from app.sessions import create_session

    # someone's approved move holds 10:00-12:00 on the 14th at Lakeview
    store.requests["req-1001"]["status"] = "approved"
    s = create_session("r-priya", "lakeview-heights")
    s.pending_draft = {
        "req_type": "move_in", "unit_id": "u-lh-1204",
        "requested_date": "2026-08-14", "time_window": "11:00-13:00",
        "checklist": [], "custom_fields": {"mover_company": "SafeShift"}, "notes": "",
    }
    with pytest.raises(HTTPException) as exc:
        confirm_request(ConfirmBody(session_id=s.id))
    assert exc.value.status_code == 409


# --- duplicates and closed-request hygiene -----------------------------------

def test_approved_request_still_blocks_a_duplicate():
    resident, community = ctx("r-sana")  # req-1003 is approved
    result = execute_tool("validate_move_request", {
        "request_type": "move_in", "unit_id": "u-pm-45", "requested_date": "2026-09-01",
    }, resident, community)
    assert any(v["rule"] == "duplicate_request" for v in result["violations"])


def test_documents_cannot_be_verified_after_rejection():
    record = store.requests["req-1005"]  # rejected, has an unverified gate pass
    record["checklist"][0]["file"] = {"filename": "x.pdf", "content_type": "application/pdf",
                                      "size": 10, "uploaded_at": "2026-08-01T00:00:00"}
    with pytest.raises(ValueError):
        store.verify_document("req-1005", "gate_pass")


def test_empty_or_mistyped_custom_fields_are_rejected():
    from app import policy as policy_engine
    pol = store.community("lakeview-heights")["policies"]["move_out"]
    assert policy_engine.missing_custom_fields(pol, {"mover_company": "   "})
    assert policy_engine.missing_custom_fields(pol, {"mover_company": 42})
    assert not policy_engine.missing_custom_fields(pol, {"mover_company": "SafeShift"})


# --- operational tasks -------------------------------------------------------

def test_admin_marks_task_done_and_it_lands_on_the_timeline():
    store.complete_task("req-1002", "elevator_booking")
    item = next(c for c in store.requests["req-1002"]["checklist"] if c["id"] == "elevator_booking")
    assert item["done"] is True
    assert store.requests["req-1002"]["timeline"][-1]["event"] == "task_completed"


def test_tasks_reject_file_operations():
    with pytest.raises(ValueError):
        store.attach_document("req-1002", "elevator_booking", filename="x.pdf",
                              content_type="application/pdf", size=10, actor_name="A")
    with pytest.raises(ValueError):
        store.verify_document("req-1002", "elevator_booking")


# --- elevator slot conflicts -------------------------------------------------

def test_overlapping_approved_move_blocks_the_elevator_slot():
    # approve Meera's 2026-08-14 10:00-12:00 move-in, then try to book the
    # same slot from another Lakeview unit
    store.requests["req-1001"]["status"] = "approved"
    resident, community = ctx("r-priya")
    result = execute_tool("validate_move_request", {
        "request_type": "move_in", "unit_id": "u-lh-1204",
        "requested_date": "2026-08-14", "time_window": "11:00-13:00",
    }, resident, community)
    assert any(v["rule"] == "elevator_conflict" for v in result["violations"])

    # a non-overlapping window the same day is fine
    result = execute_tool("validate_move_request", {
        "request_type": "move_in", "unit_id": "u-lh-1204",
        "requested_date": "2026-08-14", "time_window": "14:00-16:00",
    }, resident, community)
    assert not any(v["rule"] == "elevator_conflict" for v in result["violations"])


def test_no_elevator_no_conflict():
    # Palm Meadows has no elevator - same-slot approved moves don't clash
    resident, community = ctx("r-vikram")
    store.requests["req-1003"]["requested_date"] = "2026-09-01"
    result = execute_tool("validate_move_request", {
        "request_type": "move_in", "unit_id": "u-pm-3",
        "requested_date": "2026-09-01", "time_window": "08:00-10:00",
    }, resident, community)
    assert not any(v["rule"] == "elevator_conflict" for v in result["violations"])
