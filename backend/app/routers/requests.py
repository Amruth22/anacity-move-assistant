from fastapi import APIRouter, HTTPException

from ..models import AdminActionBody
from ..store import store

router = APIRouter(prefix="/api", tags=["requests"])


def _expand(record: dict) -> dict:
    """Attach the names a UI needs so the frontend never joins ids itself."""
    resident = store.resident(record["resident_id"]) or {}
    unit = store.unit(record["unit_id"]) or {}
    community = store.community(record["community_id"]) or {}
    return {
        **record,
        "resident_name": resident.get("name", record["resident_id"]),
        "tenancy": resident.get("tenancy", ""),
        "unit_label": unit.get("label", record["unit_id"]),
        "community_name": community.get("name", record["community_id"]),
    }


@router.get("/requests")
def list_requests(community_id: str | None = None, status: str | None = None):
    return [_expand(r) for r in store.list_requests(community_id, status)]


@router.get("/requests/{req_id}")
def get_request(req_id: str):
    record = store.requests.get(req_id)
    if record is None:
        raise HTTPException(404, "Request not found")
    return _expand(record)


@router.get("/residents/{resident_id}/requests")
def resident_requests(resident_id: str):
    if store.resident(resident_id) is None:
        raise HTTPException(404, "Unknown resident")
    return [_expand(r) for r in store.requests_for_resident(resident_id)]


@router.post("/requests/{req_id}/tasks/{item_id}/done")
def complete_task(req_id: str, item_id: str):
    """Admin marks an operational checklist item (deposit, elevator slot) done."""
    try:
        record = store.complete_task(req_id, item_id)
    except KeyError:
        raise HTTPException(404, "Request or checklist item not found")
    except ValueError as e:
        raise HTTPException(409, str(e))
    return _expand(record)


@router.post("/requests/{req_id}/action")
def admin_action(req_id: str, body: AdminActionBody):
    try:
        record = store.apply_action(req_id, body.action, body.note)
    except KeyError:
        raise HTTPException(404, "Request not found")
    except ValueError as e:
        raise HTTPException(409, str(e))
    return _expand(record)
