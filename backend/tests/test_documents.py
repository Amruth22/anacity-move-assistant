import io

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.store import store

client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh_store():
    store.seed()
    yield
    store.seed()


def upload(req_id, doc_id, resident_id, content=b"%PDF-1.4 fake", ctype="application/pdf"):
    return client.post(
        f"/api/requests/{req_id}/documents/{doc_id}/upload",
        data={"resident_id": resident_id},
        files={"file": ("noc.pdf", io.BytesIO(content), ctype)},
    )


def test_upload_attaches_file_and_logs_timeline():
    r = upload("req-1001", "rental_agreement", "r-meera")
    assert r.status_code == 200
    body = r.json()
    item = next(c for c in body["checklist"] if c["id"] == "rental_agreement")
    assert item["file"]["filename"] == "noc.pdf"
    assert not item["done"]  # uploaded, not yet verified
    assert body["timeline"][-1]["event"] == "document_uploaded"


def test_upload_by_wrong_resident_is_403():
    assert upload("req-1001", "rental_agreement", "r-priya").status_code == 403


def test_upload_rejects_unknown_type():
    r = upload("req-1001", "rental_agreement", "r-meera", ctype="application/zip")
    assert r.status_code == 422


def test_verify_requires_a_file_first():
    r = client.post("/api/requests/req-1001/documents/rental_agreement/verify")
    assert r.status_code == 409


def test_upload_then_verify_then_download():
    upload("req-1001", "rental_agreement", "r-meera")
    v = client.post("/api/requests/req-1001/documents/rental_agreement/verify")
    assert v.status_code == 200
    item = next(c for c in v.json()["checklist"] if c["id"] == "rental_agreement")
    assert item["done"]
    assert v.json()["timeline"][-1]["event"] == "document_verified"

    f = client.get("/api/requests/req-1001/documents/rental_agreement/file")
    assert f.status_code == 200
    assert f.headers["content-type"].startswith("application/pdf")


def test_cannot_replace_after_verification():
    upload("req-1001", "rental_agreement", "r-meera")
    client.post("/api/requests/req-1001/documents/rental_agreement/verify")
    assert upload("req-1001", "rental_agreement", "r-meera").status_code == 409


def test_no_uploads_on_closed_requests():
    assert upload("req-1004", "gate_pass", "r-dev").status_code == 409  # completed
