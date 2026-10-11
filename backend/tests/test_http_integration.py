"""
Real HTTP integration test: goes through the actual FastAPI app via
TestClient (real request routing, dependency injection, JSON
serialization, status codes) instead of calling backend functions
directly like the other test files in this suite do. TestClient runs the
app in-process against the ASGI interface, so this is a genuine end-to-end
check of the wiring without needing a live uvicorn server process.
"""
import time

from fastapi.testclient import TestClient

from app.main import app
from .conftest import MULTI_SUBJECT_SYLLABUS


def test_full_pipeline_over_real_http(db_session, uploads_dir):
    client = TestClient(app)

    # 1. health check
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

    # 2. real multipart upload
    with open(MULTI_SUBJECT_SYLLABUS, "rb") as f:
        r = client.post("/syllabus/upload", files={"file": ("multi-subject-sample.txt", f, "text/plain")})
    assert r.status_code == 200
    job_id = r.json()["jobId"]
    assert job_id

    # 3. poll until done
    body = {}
    for _ in range(30):
        r = client.get(f"/jobs/{job_id}")
        assert r.status_code == 200
        body = r.json()
        if body["status"] == "done":
            break
        time.sleep(0.2)
    assert body["status"] == "done"
    subjects = body["subjects"]
    assert len(subjects) == 2

    # 4. fetch a topic's content
    first_topic_id = subjects[0]["units"][0]["topics"][0]["id"]
    r = client.get(f"/topics/{first_topic_id}")
    assert r.status_code == 200
    topic_content = r.json()
    assert len(topic_content["blocks"]) > 0
    assert len(topic_content["quiz"]) > 0
    assert "image" not in topic_content  # lookup stubbed to None - key must be absent, not null

    # 5. list subtopics
    r = client.get(f"/topics/{first_topic_id}/subtopics")
    assert r.status_code == 200
    subtopics = r.json()["subtopics"]
    assert len(subtopics) > 0

    # 6. fetch one subtopic's full content
    first_subtopic_id = subtopics[0]["id"]
    r = client.get(f"/subtopics/{first_subtopic_id}")
    assert r.status_code == 200
    subtopic_content = r.json()
    assert subtopic_content["body"]
    assert subtopic_content["topic_id"] == first_topic_id

    # 7. complete the topic - and verify the completion is PERSISTED, not
    # just acknowledged. the accuracy used to be echoed back and dropped on
    # the floor, so progress existed only in the browser's localStorage.
    r = client.post(f"/topics/{first_topic_id}/complete", json={"accuracy": 88})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["accuracy"] == 88
    assert r.json()["recorded"] is True

    # it must come back in the job snapshot the frontend polls
    snapshot = client.get(f"/jobs/{job_id}").json()
    completed = [
        t
        for s in snapshot["subjects"]
        for u in s["units"]
        for t in u["topics"]
        if t["id"] == first_topic_id
    ]
    assert completed and completed[0]["completed"] is True
    assert completed[0]["accuracy"] == 88

    # 8. knowledge graph + roadmap
    r = client.get(f"/api/v1/knowledge/{job_id}/graph")
    assert r.status_code == 200
    assert r.json()["node_count"] > 0

    r = client.get(f"/api/v1/knowledge/{job_id}/roadmap/CS101")
    assert r.status_code == 200
    assert r.json()["total_steps"] > 0

    # 9. regenerate over HTTP - forces fresh content, must not duplicate subtopics
    r = client.get(f"/topics/{first_topic_id}?regenerate=true")
    assert r.status_code == 200

    r = client.get(f"/topics/{first_topic_id}/subtopics")
    assert len(r.json()["subtopics"]) == len(subtopics)

    # 10. explainability endpoint
    r = client.get(f"/topics/{first_topic_id}/explainability")
    assert r.status_code == 200
    explain = r.json()
    assert explain["available"] is True
    assert "generated_by" in explain

    # 11. reference sources: upload one, then list it back
    subject_id = first_topic_id.split("-U")[0]
    with open(MULTI_SUBJECT_SYLLABUS, "rb") as f:
        r = client.post(f"/subjects/{subject_id}/sources", files={"file": ("extra-notes.txt", f, "text/plain")})
    assert r.status_code == 200
    assert r.json()["filename"] == "extra-notes.txt"

    r = client.get(f"/subjects/{subject_id}/sources")
    assert r.status_code == 200
    assert r.json()["count"] == 1

    # 12. 404 handling - must fail cleanly with the right status code, not a 500
    r = client.get("/topics/DOES-NOT-EXIST-T1")
    assert r.status_code == 200  # this endpoint deliberately returns a soft fallback, not a 404 - see syllabus.py
    r = client.get("/subtopics/DOES-NOT-EXIST-S1")
    assert r.status_code == 404
    r = client.get(f"/api/v1/knowledge/{job_id}/roadmap/NONEXISTENT-SUBJECT")
    assert r.status_code == 404
