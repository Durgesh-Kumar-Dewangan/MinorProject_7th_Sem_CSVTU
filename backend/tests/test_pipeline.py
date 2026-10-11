"""
Full pipeline: upload -> extract -> distribute -> generate.
Covers single-subject and multi-subject syllabi, correct Unit/Topic
distribution, and the ordering/prerequisite guarantees the knowledge
graph is supposed to provide.
"""
from app.db import models
from app.db.session import SessionLocal

from .conftest import SAMPLE_SYLLABUS, MULTI_SUBJECT_SYLLABUS, upload_and_process


def test_single_subject_syllabus_parses_correctly(db_session, uploads_dir):
    sid = upload_and_process(db_session, uploads_dir, SAMPLE_SYLLABUS)

    db = SessionLocal()
    syllabus = db.query(models.Syllabus).filter(models.Syllabus.id == sid).first()
    assert syllabus.status == "parsed"
    assert syllabus.phase == "done"

    topics = (
        db.query(models.Topic)
        .join(models.Unit)
        .filter(models.Unit.syllabus_id == sid)
        .order_by(models.Topic.sequence_order)
        .all()
    )
    assert len(topics) == 6  # 2 units x 3 topics, per sample-syllabus.txt
    assert [t.title for t in topics] == [
        "Variables", "Functions", "Conditionals", "Arrays", "Linked Lists", "Hash Tables",
    ]
    db.close()


def test_sequence_order_is_strictly_increasing_across_units(db_session, uploads_dir):
    # regression test for a real bug: the knowledge graph used to only
    # chain topics within a unit, so a later unit's topic could sort
    # ahead of an earlier unit's topic
    sid = upload_and_process(db_session, uploads_dir, SAMPLE_SYLLABUS)

    db = SessionLocal()
    topics = (
        db.query(models.Topic)
        .join(models.Unit)
        .filter(models.Unit.syllabus_id == sid)
        .order_by(models.Topic.sequence_order)
        .all()
    )
    orders = [t.sequence_order for t in topics]
    assert orders == sorted(orders)
    assert orders == list(range(1, len(topics) + 1))  # no gaps, no repeats
    db.close()


def test_prerequisites_chain_correctly_across_unit_boundaries(db_session, uploads_dir):
    sid = upload_and_process(db_session, uploads_dir, SAMPLE_SYLLABUS)

    db = SessionLocal()
    topics = {t.title: t for t in db.query(models.Topic).join(models.Unit).filter(models.Unit.syllabus_id == sid).all()}

    assert topics["Variables"].prerequisite_topic_id is None  # first topic, no prerequisite
    assert topics["Arrays"].prerequisite_topic_id == topics["Conditionals"].topic_id  # crosses the unit boundary
    db.close()


def test_multi_subject_syllabus_splits_correctly(db_session, uploads_dir):
    sid = upload_and_process(db_session, uploads_dir, MULTI_SUBJECT_SYLLABUS)

    db = SessionLocal()
    syllabus = db.query(models.Syllabus).filter(models.Syllabus.id == sid).first()
    subjects = syllabus.curriculum["curriculum"]["subjects"]
    assert len(subjects) == 2
    titles = {s["subject_title"] for s in subjects}
    assert titles == {"Computer Science", "Physics"}
    db.close()


def test_no_missing_or_duplicate_topics_across_units(db_session, uploads_dir):
    sid = upload_and_process(db_session, uploads_dir, MULTI_SUBJECT_SYLLABUS)

    db = SessionLocal()
    units = db.query(models.Unit).filter(models.Unit.syllabus_id == sid).all()
    assert len(units) == 4  # 2 subjects x 2 units each

    all_topic_ids = []
    for unit in units:
        topics = db.query(models.Topic).filter(models.Topic.unit_id == unit.id).all()
        assert len(topics) == 3  # every unit in the sample has exactly 3 topics
        all_topic_ids.extend(t.topic_id for t in topics)

    assert len(all_topic_ids) == len(set(all_topic_ids)), "duplicate topic_id found across units"

    orphans = db.query(models.Topic).filter(models.Topic.unit_id.is_(None)).count()
    assert orphans == 0
    db.close()


def test_duplicate_upload_does_not_crash_and_disambiguates_subject_ids(db_session, uploads_dir):
    # regression test for a real bug: two separate uploads that happen to
    # produce the same subject/unit/topic naming used to crash the second
    # upload with a database integrity error, and the crash handler itself
    # was broken (tried to commit without rolling back first), so the
    # failure was never even recorded
    sid1 = upload_and_process(db_session, uploads_dir, SAMPLE_SYLLABUS)
    sid2 = upload_and_process(db_session, uploads_dir, SAMPLE_SYLLABUS)

    db = SessionLocal()
    s1 = db.query(models.Syllabus).filter(models.Syllabus.id == sid1).first()
    s2 = db.query(models.Syllabus).filter(models.Syllabus.id == sid2).first()
    assert s1.status == "parsed"
    assert s2.status == "parsed"  # must succeed, not crash

    ids1 = {t.topic_id for t in db.query(models.Topic).join(models.Unit).filter(models.Unit.syllabus_id == sid1).all()}
    ids2 = {t.topic_id for t in db.query(models.Topic).join(models.Unit).filter(models.Unit.syllabus_id == sid2).all()}
    assert ids1.isdisjoint(ids2), "the two syllabi's topic_ids must not collide"
    db.close()


def test_a_genuinely_unrelated_failure_is_recorded_correctly(db_session, uploads_dir):
    # regression test: the exception handler used to commit() without
    # rolling back first, so if the original error was itself a db error,
    # the handler crashed too and the syllabus was left stuck on
    # "processing" forever with no error message ever recorded
    from app.db import models
    from app.api.routers.syllabus import process_syllabus

    syllabus = models.Syllabus(
        original_filename="bad.txt",
        stored_path="/nonexistent/path/does-not-exist.txt",
        file_type="text",
        status="uploaded",
    )
    db_session.add(syllabus)
    db_session.commit()
    db_session.refresh(syllabus)
    sid = str(syllabus.id)

    process_syllabus(sid)

    db = SessionLocal()
    s = db.query(models.Syllabus).filter(models.Syllabus.id == sid).first()
    assert s.status == "failed"
    assert s.error_message  # a real message must be recorded, not silently stuck
    db.close()
