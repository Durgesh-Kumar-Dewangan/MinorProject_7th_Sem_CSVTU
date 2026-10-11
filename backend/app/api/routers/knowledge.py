from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from uuid import UUID
from app.db.session import get_db
from app.db import models
from app.services.knowledge_graph import (
    build_knowledge_graph,
    generate_roadmap,
    graph_to_dict,
    dict_to_graph,
)

router = APIRouter()


class IngestRequest(BaseModel):
    subject_id: str
    topic_id: str
    text: str
    source: str = "manual"


class SearchRequest(BaseModel):
    subject_id: str
    query: str
    top_k: int = 5


def _load_graph(syllabus: models.Syllabus):
    """Prefer the graph stored during the "distribute" pipeline stage
    (see app/api/routers/syllabus.py::process_syllabus) so this doesn't
    redo work; fall back to rebuilding from curriculum for syllabi that
    were processed before that stage existed.
    """
    if syllabus.knowledge_graph:
        return dict_to_graph(syllabus.knowledge_graph)
    if syllabus.curriculum:
        return build_knowledge_graph(syllabus.curriculum)
    return None


@router.get("/{syllabus_id}/graph")
def get_knowledge_graph(syllabus_id: UUID, db: Session = Depends(get_db)):
    # syllabus_id comes in as a real UUID object (FastAPI parses the URL
    # path param per the type hint above), but Syllabus.id is a plain
    # String(36) column - comparing a UUID object against a string column
    # never matches, so this has to be stringified first or every request
    # here 404s no matter what
    syllabus = db.query(models.Syllabus).filter(models.Syllabus.id == str(syllabus_id)).first()
    if not syllabus:
        raise HTTPException(404, "Syllabus not found")

    G = _load_graph(syllabus)
    if G is None:
        raise HTTPException(400, "Syllabus has not been parsed yet")

    return {
        "syllabus_id": str(syllabus_id),
        "graph": graph_to_dict(G),
        "node_count": G.number_of_nodes(),
        "edge_count": G.number_of_edges(),
    }


@router.get("/{syllabus_id}/roadmap/{subject_id}")
def get_roadmap(
    syllabus_id: UUID,
    subject_id: str,
    db: Session = Depends(get_db),
):
    # same UUID-vs-string issue as get_knowledge_graph above
    syllabus = db.query(models.Syllabus).filter(models.Syllabus.id == str(syllabus_id)).first()
    if not syllabus:
        raise HTTPException(404, "Syllabus not found")

    G = _load_graph(syllabus)
    if G is None:
        raise HTTPException(400, "Syllabus has not been parsed yet")

    roadmap = generate_roadmap(G, subject_id)

    if not roadmap:
        raise HTTPException(404, f"No roadmap found for subject_id={subject_id}")

    return {
        "syllabus_id": str(syllabus_id),
        "subject_id": subject_id,
        "roadmap": roadmap,
        "total_steps": len(roadmap),
    }


@router.post("/ingest")
def ingest_text(req: IngestRequest):
    try:
        from app.services.embeddings import ingest_document_for_topic
    except Exception as exc:
        raise HTTPException(503, f"Knowledge ingestion dependencies are unavailable: {exc}") from exc

    # Chunk text is always stored even when no vectors can be made, so this
    # still succeeds (and keyword/BM25 retrieval still works) without an
    # embedding model - see SubjectFAISSIndex.add_chunks.
    n = ingest_document_for_topic(
        subject_id=req.subject_id,
        topic_id=req.topic_id,
        document_text=req.text,
        source=req.source,
    )
    return {
        "status": "ok",
        "chunks_added": n,
        "subject_id": req.subject_id,
        "topic_id": req.topic_id,
    }


@router.post("/search")
def search_vectors(req: SearchRequest):
    try:
        from app.services.embeddings import SubjectFAISSIndex
    except Exception as exc:
        raise HTTPException(503, f"Knowledge search dependencies are unavailable: {exc}") from exc

    index = SubjectFAISSIndex(req.subject_id)
    try:
        results = index.search(req.query, top_k=req.top_k)
    except Exception as exc:
        # The import above only proves the modules exist; actually embedding
        # the query can still fail at call time (model never downloaded, no
        # network on first use). That's an unavailable dependency, not a bug
        # in the request - 503 with the reason, not an opaque 500. The
        # lesson pipeline hits the same wall and degrades to keyword-only
        # retrieval; this endpoint is vector search by definition, so it has
        # nothing to degrade to and says so instead.
        raise HTTPException(503, f"Vector search is unavailable (no embedding model): {exc}") from exc
    return {
        "subject_id": req.subject_id,
        "query": req.query,
        "results": results,
    }
