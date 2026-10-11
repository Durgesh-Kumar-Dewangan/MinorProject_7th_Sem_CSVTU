"""
Knowledge graph and roadmap endpoints. Includes a regression test for a
real bug: these endpoints always 404'd because the path parameter was
typed as UUID and compared directly against a String(36) database column.
"""
import uuid as uuid_module

from app.db.session import SessionLocal
from app.api.routers.knowledge import get_knowledge_graph, get_roadmap

from .conftest import MULTI_SUBJECT_SYLLABUS, upload_and_process


def test_knowledge_graph_endpoint_returns_real_data(db_session, uploads_dir):
    sid = upload_and_process(db_session, uploads_dir, MULTI_SUBJECT_SYLLABUS)

    db = SessionLocal()
    result = get_knowledge_graph(uuid_module.UUID(sid), db)
    assert result["node_count"] > 0
    assert result["edge_count"] > 0
    db.close()


def test_roadmap_endpoint_returns_full_ordered_sequence(db_session, uploads_dir):
    sid = upload_and_process(db_session, uploads_dir, MULTI_SUBJECT_SYLLABUS)

    db = SessionLocal()
    result = get_roadmap(uuid_module.UUID(sid), "P101", db)
    assert result["subject_id"] == "P101"
    assert result["total_steps"] > 0
    db.close()
