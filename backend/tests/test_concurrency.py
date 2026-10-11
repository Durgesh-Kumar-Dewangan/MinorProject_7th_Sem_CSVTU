"""
Concurrency: two or more requests for the same not-yet-generated topic
must never both trigger a real generation call.
"""
import threading
import time

from app.db import models
from app.db.session import SessionLocal
import app.api.routers.syllabus as syllabus_router

from .conftest import SAMPLE_SYLLABUS, upload_and_process


def test_concurrent_requests_produce_exactly_one_generation_call(db_session, uploads_dir, monkeypatch):
    upload_and_process(db_session, uploads_dir, SAMPLE_SYLLABUS)

    call_count = {"n": 0}
    call_lock = threading.Lock()

    def fake_generate_topic_lesson(**kwargs):
        with call_lock:
            call_count["n"] += 1
        time.sleep(0.2)  # widen the race window so a real bug would actually get hit
        return None  # force the template fallback, deterministic and fast

    monkeypatch.setattr(syllabus_router, "generate_topic_lesson", fake_generate_topic_lesson)

    results = []

    def worker():
        db = SessionLocal()
        topic = db.query(models.Topic).filter(models.Topic.topic_id == "CS101-U2-T2").first()
        syllabus_router._ensure_topic_generated(topic, db)
        db.refresh(topic)
        results.append(len(topic.subtopics) > 0)
        db.close()

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert call_count["n"] == 1, f"expected exactly 1 generation call, got {call_count['n']}"
    assert all(results), "every concurrent caller should still receive valid content"

    db = SessionLocal()
    topic = db.query(models.Topic).filter(models.Topic.topic_id == "CS101-U2-T2").first()
    subtopic_count = db.query(models.Subtopic).filter(models.Subtopic.topic_id == topic.id).count()
    assert subtopic_count > 0
    db.close()
