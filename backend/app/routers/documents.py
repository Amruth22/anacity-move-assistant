"""Document upload / view / verify for checklist items.

Files land on disk under backend/uploads/{request_id}/; metadata lives on the
checklist item in the store. Identity is demo-level like the rest of the app:
the resident persona id comes with the form and must own the request.
"""

from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ..store import store

router = APIRouter(prefix="/api/requests", tags=["documents"])

UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "uploads"

MAX_SIZE = 5 * 1024 * 1024
ALLOWED = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


def _stored_path(req_id: str, doc_id: str, ext: str) -> Path:
    return UPLOAD_DIR / req_id / f"{doc_id}{ext}"


@router.post("/{req_id}/documents/{doc_id}/upload")
async def upload_document(req_id: str, doc_id: str, file: UploadFile, resident_id: str = Form(...)):
    record = store.requests.get(req_id)
    if record is None:
        raise HTTPException(404, "Request not found")
    if record["resident_id"] != resident_id:
        raise HTTPException(403, "This request belongs to another resident")
    if file.content_type not in ALLOWED:
        raise HTTPException(422, "Only PDF, PNG, JPEG or WebP files are accepted")

    data = await file.read()
    if len(data) > MAX_SIZE:
        raise HTTPException(413, "File too large (5 MB limit)")

    resident = store.resident(resident_id)
    try:
        record = store.attach_document(
            req_id, doc_id,
            filename=file.filename or "document",
            content_type=file.content_type,
            size=len(data),
            actor_name=resident["name"] if resident else resident_id,
        )
    except KeyError:
        raise HTTPException(404, "No such checklist item")
    except ValueError as e:
        raise HTTPException(409, str(e))

    # one file per checklist item - replacing is just overwriting
    dest = _stored_path(req_id, doc_id, ALLOWED[file.content_type])
    dest.parent.mkdir(parents=True, exist_ok=True)
    for old in dest.parent.glob(f"{doc_id}.*"):
        old.unlink()
    dest.write_bytes(data)
    return record


@router.get("/{req_id}/documents/{doc_id}/file")
def get_document(req_id: str, doc_id: str):
    record = store.requests.get(req_id)
    if record is None:
        raise HTTPException(404, "Request not found")
    item = next((c for c in record["checklist"] if c["id"] == doc_id), None)
    if item is None or not item.get("file"):
        raise HTTPException(404, "No file uploaded for this item")
    ext = ALLOWED.get(item["file"]["content_type"], "")
    path = _stored_path(req_id, doc_id, ext)
    if not path.exists():
        raise HTTPException(410, "File is gone (server restarted since upload)")
    return FileResponse(path, media_type=item["file"]["content_type"], filename=item["file"]["filename"])


@router.post("/{req_id}/documents/{doc_id}/verify")
def verify_document(req_id: str, doc_id: str):
    try:
        return store.verify_document(req_id, doc_id)
    except KeyError:
        raise HTTPException(404, "Request or checklist item not found")
    except ValueError as e:
        raise HTTPException(409, str(e))
