"""
Content generation: subtopics as real database rows, caching, forced
regeneration, and the "image only if actually found, no placeholder" rule.
"""
from app.db import models
from app.db.session import SessionLocal
from app.api.routers.syllabus import get_topic_content, list_subtopics, get_subtopic_content

from .conftest import SAMPLE_SYLLABUS, upload_and_process


def test_topic_content_generates_real_subtopic_rows(db_session, uploads_dir):
    upload_and_process(db_session, uploads_dir, SAMPLE_SYLLABUS)

    db = SessionLocal()
    result = get_topic_content("CS101-U1-T1", regenerate=False, db=db)
    assert result["status"] == "ready"
    assert len(result["blocks"]) > 0

    topic = db.query(models.Topic).filter(models.Topic.topic_id == "CS101-U1-T1").first()
    subtopics = db.query(models.Subtopic).filter(models.Subtopic.topic_id == topic.id).all()
    assert len(subtopics) == len(result["blocks"])
    for s in subtopics:
        assert s.subtopic_id.startswith("CS101-U1-T1-S")
        assert s.body  # not empty/placeholder
    db.close()


def test_different_topics_get_genuinely_distinct_content(db_session, uploads_dir):
    upload_and_process(db_session, uploads_dir, SAMPLE_SYLLABUS)

    db = SessionLocal()
    r1 = get_topic_content("CS101-U1-T1", regenerate=False, db=db)  # Variables
    r2 = get_topic_content("CS101-U2-T1", regenerate=False, db=db)  # Arrays

    body1 = r1["blocks"][0]["body"]
    body2 = r2["blocks"][0]["body"]
    assert body1 != body2
    assert "Variables" in body1
    assert "Arrays" in body2
    db.close()


def test_content_is_cached_not_regenerated_on_repeat_visits(db_session, uploads_dir):
    upload_and_process(db_session, uploads_dir, SAMPLE_SYLLABUS)

    db = SessionLocal()
    r1 = get_topic_content("CS101-U1-T2", regenerate=False, db=db)
    r2 = get_topic_content("CS101-U1-T2", regenerate=False, db=db)
    assert r1["blocks"] == r2["blocks"]  # identical, not regenerated
    db.close()


def test_regenerate_replaces_subtopics_without_duplicating(db_session, uploads_dir):
    # regression test: forced regeneration used to risk leaving old
    # subtopic rows alongside the new ones if they weren't cleared first
    upload_and_process(db_session, uploads_dir, SAMPLE_SYLLABUS)

    db = SessionLocal()
    get_topic_content("CS101-U1-T3", regenerate=False, db=db)
    topic = db.query(models.Topic).filter(models.Topic.topic_id == "CS101-U1-T3").first()
    count_before = db.query(models.Subtopic).filter(models.Subtopic.topic_id == topic.id).count()
    assert count_before > 0

    get_topic_content("CS101-U1-T3", regenerate=True, db=db)
    count_after = db.query(models.Subtopic).filter(models.Subtopic.topic_id == topic.id).count()
    assert count_after == count_before  # replaced, not duplicated
    db.close()


def test_topic_content_has_no_image_key_when_none_found(db_session, uploads_dir):
    # The "no placeholder" rule: when no image is found the key must be
    # completely absent - not null, not an empty object - so the frontend
    # has nothing to branch on but "is this key present".
    #
    # The lookup is stubbed to None by conftest's offline_image_lookup
    # fixture. It used to rely on the dev sandbox simply having no route to
    # the image API, which meant this test asserted "no image" on a machine
    # with no internet and failed on any machine that has it.
    upload_and_process(db_session, uploads_dir, SAMPLE_SYLLABUS)

    db = SessionLocal()
    result = get_topic_content("CS101-U1-T1", regenerate=False, db=db)
    assert "image" not in result
    db.close()


def test_image_key_present_only_when_an_image_is_found(db_session, uploads_dir, monkeypatch):
    # the other half of the same rule: when the lookup DOES return an image,
    # it must be passed through to the client intact. overrides conftest's
    # autouse stub with one that returns a real-shaped result.
    import app.api.routers.syllabus as syllabus_router

    found = {
        "url": "https://example.test/diagram.png",
        "thumbnail_url": "https://example.test/diagram-thumb.png",
        "title": "Variables diagram",
        "creator": "Someone",
        "license": "cc-by",
        "source_url": "https://example.test/page",
    }
    monkeypatch.setattr(syllabus_router, "find_topic_image", lambda query: found)

    upload_and_process(db_session, uploads_dir, SAMPLE_SYLLABUS)

    db = SessionLocal()
    result = get_topic_content("CS101-U1-T1", regenerate=False, db=db)
    assert result["image"] == found
    db.close()


def test_list_subtopics_endpoint(db_session, uploads_dir):
    upload_and_process(db_session, uploads_dir, SAMPLE_SYLLABUS)

    db = SessionLocal()
    result = list_subtopics("CS101-U1-T1", db=db)
    assert result["topic_id"] == "CS101-U1-T1"
    assert len(result["subtopics"]) > 0
    for s in result["subtopics"]:
        assert s["id"].startswith("CS101-U1-T1-S")
        assert s["title"]
    db.close()


def test_get_subtopic_content_endpoint_returns_full_context(db_session, uploads_dir):
    upload_and_process(db_session, uploads_dir, SAMPLE_SYLLABUS)

    db = SessionLocal()
    subs = list_subtopics("CS101-U1-T1", db=db)
    first_id = subs["subtopics"][0]["id"]

    result = get_subtopic_content(first_id, db=db)
    assert result["subtopic_id"] == first_id
    assert result["body"]
    assert result["topic_id"] == "CS101-U1-T1"
    assert result["topic_title"] == "Variables"
    assert result["unit_title"] == "Fundamentals"
    db.close()
