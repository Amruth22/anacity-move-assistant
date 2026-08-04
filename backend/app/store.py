"""In-memory data store, seeded from JSON at startup.

Deliberately a plain object with dicts inside - for a prototype this keeps the
whole persistence story in one file. Swapping to Postgres later means
reimplementing these methods, nothing else. State resets on restart; that's a
stated assumption in the docs.
"""

import json
from datetime import datetime

from .config import SEED_DIR

# statuses that block a second request for the same unit+type. Approved counts:
# the move hasn't happened yet, so a new request would still be a duplicate.
OPEN_STATUSES = {"submitted", "needs_info", "approved"}

# statuses in which the resident can still change or reply to the request
RESIDENT_EDITABLE = {"submitted", "needs_info"}

# statuses from which the resident can withdraw entirely
CANCELLABLE = {"submitted", "needs_info", "approved"}

# which admin actions are legal from which status. request_info is legal from
# needs_info too - admins sometimes have to ask twice.
TRANSITIONS = {
    "approve": {"submitted", "needs_info"},
    "reject": {"submitted", "needs_info"},
    "request_info": {"submitted", "needs_info"},
    "complete": {"approved"},
}

ACTION_TO_STATUS = {
    "approve": "approved",
    "reject": "rejected",
    "request_info": "needs_info",
    "complete": "completed",
}


def _windows_overlap(a: str | None, b: str | None) -> bool:
    """'10:00-12:00' vs '11:00-13:00' -> True. A missing or malformed window
    is treated as all-day, so it conservatively overlaps everything."""
    def parse(w):
        try:
            start, end = [p.strip() for p in w.split("-")]
            return start, end
        except (AttributeError, ValueError):
            return None
    pa, pb = parse(a), parse(b)
    if pa is None or pb is None:
        return True
    return pa[0] < pb[1] and pb[0] < pa[1]


class Store:
    def __init__(self):
        self.communities: dict[str, dict] = {}
        self.units: dict[str, dict] = {}
        self.residents: dict[str, dict] = {}
        self.requests: dict[str, dict] = {}
        self._next_id = 2000

    def seed(self):
        communities = json.loads((SEED_DIR / "communities.json").read_text(encoding="utf-8"))
        data = json.loads((SEED_DIR / "seed_data.json").read_text(encoding="utf-8"))
        self.communities = {c["id"]: c for c in communities}
        self.units = {u["id"]: u for u in data["units"]}
        self.residents = {r["id"]: r for r in data["residents"]}
        self.requests = {r["id"]: r for r in data["requests"]}
        # normalize seed records so the rest of the code never branches on
        # missing keys: every request knows when it was submitted, every
        # checklist item knows its kind
        for r in self.requests.values():
            r.setdefault("submitted_on", r["timeline"][0]["ts"][:10] if r["timeline"] else None)
            for item in r["checklist"]:
                item.setdefault("kind", "document")
                item.setdefault("done", False)
                item.setdefault("file", None)

    # --- lookups -----------------------------------------------------------

    def community(self, community_id: str) -> dict | None:
        return self.communities.get(community_id)

    def resident(self, resident_id: str) -> dict | None:
        return self.residents.get(resident_id)

    def unit(self, unit_id: str) -> dict | None:
        return self.units.get(unit_id)

    def residents_in(self, community_id: str) -> list[dict]:
        return [r for r in self.residents.values() if r["community_id"] == community_id]

    def list_requests(self, community_id: str | None = None, status: str | None = None) -> list[dict]:
        out = list(self.requests.values())
        if community_id:
            out = [r for r in out if r["community_id"] == community_id]
        if status:
            out = [r for r in out if r["status"] == status]
        out.sort(key=lambda r: r["timeline"][0]["ts"] if r["timeline"] else "", reverse=True)
        return out

    def requests_for_resident(self, resident_id: str) -> list[dict]:
        return [r for r in self.list_requests() if r["resident_id"] == resident_id]

    def open_request_for_unit(self, unit_id: str, req_type: str) -> dict | None:
        for r in self.requests.values():
            if r["unit_id"] == unit_id and r["type"] == req_type and r["status"] in OPEN_STATUSES:
                return r
        return None

    # --- writes ------------------------------------------------------------

    def create_request(self, *, req_type: str, resident: dict, unit_id: str,
                       requested_date: str, time_window: str, checklist: list[dict],
                       custom_fields: dict, notes: str) -> dict:
        req_id = f"req-{self._next_id}"
        self._next_id += 1
        now = datetime.now()
        record = {
            "id": req_id,
            "type": req_type,
            "resident_id": resident["id"],
            "community_id": resident["community_id"],
            "unit_id": unit_id,
            "requested_date": requested_date,
            "time_window": time_window,
            "status": "submitted",
            # notice-period compliance is judged against this date forever  - 
            # a request that was valid when filed doesn't rot while it waits
            "submitted_on": now.date().isoformat(),
            "checklist": checklist,
            "custom_fields": custom_fields,
            "notes": notes,
            "timeline": [{
                "ts": now.isoformat(timespec="seconds"),
                "actor": "resident",
                "event": "submitted",
                "note": "Request created via assistant",
            }],
            "copilot": None,
        }
        self.requests[req_id] = record
        return record

    def attach_document(self, req_id: str, doc_id: str, *, filename: str,
                        content_type: str, size: int, actor_name: str) -> dict:
        """Record an uploaded file against a checklist item. Re-uploads replace
        the previous file until an admin has verified the item."""
        record = self.requests.get(req_id)
        if record is None:
            raise KeyError(req_id)
        if record["status"] not in OPEN_STATUSES:
            raise ValueError(f"Documents can't be added to a request in status '{record['status']}'")
        item = next((c for c in record["checklist"] if c["id"] == doc_id), None)
        if item is None:
            raise KeyError(doc_id)
        if item.get("kind", "document") != "document":
            raise ValueError(f"'{item['name']}' doesn't take a file upload")
        if item.get("done"):
            raise ValueError(f"'{item['name']}' is already verified")
        item["file"] = {
            "filename": filename,
            "content_type": content_type,
            "size": size,
            "uploaded_at": datetime.now().isoformat(timespec="seconds"),
        }
        record["timeline"].append({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "actor": "resident",
            "event": "document_uploaded",
            "note": f"{actor_name} uploaded {item['name']} ({filename})",
        })
        record["copilot"] = None  # new evidence, stale assessment
        return record

    def verify_document(self, req_id: str, doc_id: str) -> dict:
        record = self.requests.get(req_id)
        if record is None:
            raise KeyError(req_id)
        if record["status"] not in OPEN_STATUSES:
            raise ValueError(f"Documents can't be verified on a request in status '{record['status']}'")
        item = next((c for c in record["checklist"] if c["id"] == doc_id), None)
        if item is None:
            raise KeyError(doc_id)
        if item.get("kind", "document") != "document":
            raise ValueError(f"'{item['name']}' is a task, not a document. Mark it done instead.")
        if not item.get("file"):
            raise ValueError(f"No file uploaded for '{item['name']}' yet")
        item["done"] = True
        record["timeline"].append({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "actor": "admin",
            "event": "document_verified",
            "note": f"{item['name']} verified",
        })
        record["copilot"] = None
        return record

    def complete_task(self, req_id: str, item_id: str) -> dict:
        """Admin marks an operational item (deposit paid, elevator booked) done."""
        record = self.requests.get(req_id)
        if record is None:
            raise KeyError(req_id)
        if record["status"] not in OPEN_STATUSES:
            raise ValueError(f"Tasks can't be updated on a request in status '{record['status']}'")
        item = next((c for c in record["checklist"] if c["id"] == item_id), None)
        if item is None:
            raise KeyError(item_id)
        if item.get("kind", "document") != "task":
            raise ValueError(f"'{item['name']}' is a document. Verify its upload instead.")
        if item.get("done"):
            raise ValueError(f"'{item['name']}' is already marked done")
        item["done"] = True
        record["timeline"].append({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "actor": "admin",
            "event": "task_completed",
            "note": f"{item['name']}: done",
        })
        record["copilot"] = None
        return record

    def update_request(self, req_id: str, *, requested_date: str | None = None,
                       time_window: str | None = None, custom_fields: dict | None = None,
                       notes: str | None = None, message: str = "", actor_name: str) -> dict:
        """Resident edits or replies to their own open request. Any touch on a
        needs_info request sends it back to the admin as submitted - that IS
        the resident's answer to 'we need more information'."""
        record = self.requests.get(req_id)
        if record is None:
            raise KeyError(req_id)
        if record["status"] not in RESIDENT_EDITABLE:
            raise ValueError(f"A request in status '{record['status']}' can't be changed. "
                            "Ask the admin desk if something is wrong.")

        changes = []
        if requested_date and requested_date != record["requested_date"]:
            changes.append(f"date {record['requested_date']} → {requested_date}")
            record["requested_date"] = requested_date
        if time_window and time_window != record["time_window"]:
            changes.append(f"time {record['time_window']} → {time_window}")
            record["time_window"] = time_window
        if custom_fields:
            record["custom_fields"] = {**record["custom_fields"], **custom_fields}
            changes.append("details updated")
        if notes is not None and notes != record["notes"]:
            record["notes"] = notes
            changes.append("notes updated")

        now = datetime.now().isoformat(timespec="seconds")
        if changes or message:
            record["timeline"].append({
                "ts": now,
                "actor": "resident",
                "event": "updated" if changes else "resident_reply",
                "note": "; ".join(filter(None, ["; ".join(changes), message])) or message,
            })
        if record["status"] == "needs_info":
            record["status"] = "submitted"
            record["timeline"].append({
                "ts": now,
                "actor": "resident",
                "event": "resubmitted",
                "note": f"{actor_name} responded and resubmitted for review",
            })
        record["copilot"] = None
        return record

    def cancel_request(self, req_id: str, actor_name: str) -> dict:
        record = self.requests.get(req_id)
        if record is None:
            raise KeyError(req_id)
        if record["status"] not in CANCELLABLE:
            raise ValueError(f"A request in status '{record['status']}' can't be cancelled.")
        record["status"] = "cancelled"
        record["timeline"].append({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "actor": "resident",
            "event": "cancelled",
            "note": f"Withdrawn by {actor_name}",
        })
        record["copilot"] = None
        return record

    def approved_moves_overlapping(self, community_id: str, on_date: str,
                                   window: str | None, exclude_id: str | None = None) -> list[dict]:
        """Approved moves in this community on the same date whose time windows
        overlap the given one. Used for elevator-slot conflict checks."""
        out = []
        for r in self.requests.values():
            if r["id"] == exclude_id or r["community_id"] != community_id:
                continue
            if r["status"] != "approved" or r["requested_date"] != on_date:
                continue
            if _windows_overlap(window, r.get("time_window")):
                out.append(r)
        return out

    def apply_action(self, req_id: str, action: str, note: str | None) -> dict:
        record = self.requests.get(req_id)
        if record is None:
            raise KeyError(req_id)
        if record["status"] not in TRANSITIONS[action]:
            raise ValueError(f"Cannot {action} a request in status '{record['status']}'")
        note = (note or "").strip()
        # a resident-facing bounce-back with no explanation is useless - and an
        # approval over pending checklist items must say why on the record
        if action in ("request_info", "reject") and not note:
            raise ValueError("A note to the resident is required for this action.")
        if action == "approve":
            pending = [c["name"] for c in record["checklist"] if not c["done"]]
            if pending and not note:
                raise ValueError(
                    "Still pending: " + ", ".join(pending) + ". "
                    "Approving anyway needs a note recording why."
                )
        record["status"] = ACTION_TO_STATUS[action]
        record["timeline"].append({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "actor": "admin",
            "event": record["status"],
            "note": note or "",
        })
        # any admin action changes the facts, so a cached assessment is stale
        record["copilot"] = None
        return record


store = Store()
store.seed()
