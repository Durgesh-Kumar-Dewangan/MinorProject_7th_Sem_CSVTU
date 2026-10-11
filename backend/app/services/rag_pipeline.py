"""
End-to-end pipeline for one topic, following the project methodology:

  Phase 1  Document processing   done at upload time (parser/ocr/multimodal
                                 -> chunking -> embeddings -> FAISS)
  Phase 2  Multi-RAG retrieval   retrieval.hybrid_retrieve (vector+BM25 ->
                                 RRF -> re-rank -> context selection)
  Phase 3  LLM generation        llm_client (prompt construction + provider
                                 call) + optimize_response() below
  Phase 4  Explainable AI        xai.py (attribution, relevance, evidence
                                 trace, Shapley/SHAP)
  Phase 5  Responsible AI        validation.py (groundedness, faithfulness,
                                 hallucination, similarity, evidence
                                 verification, trust score)
  ->       Final trustworthy response = lesson + trust score + evidence
"""
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.services import validation, xai
from app.services.multimodal import modality_of
from app.services.retrieval import hybrid_retrieve, query_coverage, rank_excerpt
from app.services.similarity import split_sentences

LOW_TRUST_REGENERATE_BELOW = 0.45  # one strict-mode retry when trust is "low"


def optimize_response(body: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """Phase 3 response optimization: tidy an LLM/template response before it is validated and stored."""
    notes: List[str] = []

    seen, blocks = set(), []
    for b in body.get("blocks") or []:
        title = re.sub(r"\s+", " ", str(b.get("title", "")).strip())
        text = re.sub(r"[ \t]+", " ", str(b.get("body", "")).strip())
        key = title.lower()
        if len(text) < 20 or key in seen:
            notes.append(f"dropped block '{title[:40]}' (empty/duplicate)")
            continue
        seen.add(key)
        blocks.append({**b, "title": title, "body": text})
    if blocks:
        body["blocks"] = blocks

    fixed_quiz = []
    for q in body.get("quiz") or []:
        opts = q.get("options") or []
        if len(opts) < 2:
            notes.append("dropped quiz item with fewer than 2 options")
            continue
        ans = q.get("answer")
        if not isinstance(ans, int) or not 0 <= ans < len(opts):
            notes.append("clamped out-of-range quiz answer index")
            q = {**q, "answer": 0}
        fixed_quiz.append(q)
    if body.get("quiz") is not None:
        body["quiz"] = fixed_quiz
    return body, notes


def extract_evidence_sentences(topic_title: str, chunks: List[Dict[str, Any]], max_sentences: int = 3) -> Optional[Dict[str, Any]]:
    """Best sentences (verbatim) from the retrieved evidence that mention the topic."""
    scored = []
    for ci, c in enumerate(chunks):
        for si, sent in enumerate(split_sentences(c["text"])):
            cov = query_coverage(topic_title, sent)
            if cov > 0:
                scored.append((cov, -ci, -si, ci, si, sent, c.get("source") or "syllabus"))
    if not scored:
        return None
    scored.sort(reverse=True)
    top = sorted(scored[:max_sentences], key=lambda t: (t[3], t[4]))
    sources = []
    for t in top:
        if t[6] not in sources:
            sources.append(t[6])
    return {"sentences": [t[5] for t in top], "sources": sources}


def _analyse(blocks, chunks, query) -> Dict[str, Any]:
    ev = validation.build_evidence(blocks, chunks)
    verdicts = validation.verify_evidence(ev) if ev else []
    report = validation.validate_response(ev, query=query, verdicts=verdicts)
    shap = xai.shapley_attribution(ev)
    return {
        "report": report,
        "shap": shap,
        "trace": xai.evidence_trace(ev, verdicts),
        "relevance": xai.context_relevance(ev, chunks, shap, verdicts),
    }


def run_topic_pipeline(
    *,
    topic_title: str,
    unit_title: str,
    subject_title: str,
    prerequisite_title: Optional[str],
    sequence_order: Optional[int],
    raw_text: str,
    subject_id: Optional[str],
    generate: Callable[..., Optional[Dict[str, Any]]],
    template: Callable[[List[Dict[str, Any]]], Dict[str, Any]],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    query = f"{topic_title} {unit_title}".strip()

    # ---- Phase 2: multi-RAG retrieval ----
    chunks: List[Dict[str, Any]] = []
    retrieval: Dict[str, Any] = {"method": "none", "vector_used": False, "keyword_used": False,
                                 "candidates": 0, "reranked": False, "selected": 0, "query": query}
    if subject_id:
        try:
            chunks, retrieval = hybrid_retrieve(subject_id, query, top_k=4)
        except Exception:
            chunks = []
    index_retrieval_used = bool(chunks)
    if not chunks:
        chunks = rank_excerpt(raw_text, query, top_k=4)
        retrieval = {**retrieval, "method": "excerpt-fallback" if chunks else "none", "selected": len(chunks)}

    # ---- Phase 3: LLM response generation (+ optimization) ----
    # provider_attempts is filled in by llm_client with one entry per
    # provider tried and what happened to it, so a rejected key or a retired
    # model name shows up in the report instead of silently looking like
    # "no LLM configured".
    provider_attempts: List[Dict[str, str]] = []
    gen_kwargs = dict(
        topic_title=topic_title, unit_title=unit_title, subject_title=subject_title,
        prerequisite_title=prerequisite_title, sequence_order=sequence_order,
        source_excerpt=raw_text, subject_id=subject_id, context_chunks=chunks,
        attempts=provider_attempts,
    )
    body = generate(**gen_kwargs)
    optimization: Dict[str, Any] = {"regenerated": False, "notes": []}
    if body is None:
        body = template(chunks)
    body, notes = optimize_response(body)
    optimization["notes"] = notes

    # ---- Phases 4 + 5: explain and validate ----
    analysis = _analyse(body.get("blocks") or [], chunks, query)
    trust = analysis["report"].get("trust_score")

    if (body.get("_generated_by") not in (None, "template") and trust is not None
            and trust < LOW_TRUST_REGENERATE_BELOW):
        retry = generate(**gen_kwargs, strict=True)
        if retry is not None:
            retry, retry_notes = optimize_response(retry)
            retry_analysis = _analyse(retry.get("blocks") or [], chunks, query)
            retry_trust = retry_analysis["report"].get("trust_score")
            optimization.update(regenerated=True, trust_before=trust, trust_after=retry_trust)
            if retry_trust is not None and retry_trust > trust:
                body, analysis, optimization["notes"] = retry, retry_analysis, retry_notes
                optimization["kept"] = "strict-regeneration"
            else:
                optimization["kept"] = "first-draft"

    report = analysis["report"]
    if not report.get("available") and body.get("_generated_by") == "template":
        report = {**report, "reason": "the built-in template makes no claims about the subject, so there is nothing to "
                  "validate - upload a reference source or configure an LLM provider for evidence-grounded lessons"}
    public_chunks = [
        {
            "snippet": c["text"][:200],
            "source": c.get("source") or "syllabus",
            "modality": modality_of(c["text"]),
            "score": c.get("score"),
            "vector_score": c.get("vector_score"),
            "keyword_score": c.get("keyword_score"),
            "rank": c.get("rank"),
        }
        for c in chunks
    ] if index_retrieval_used else []

    explainability = {
        "generated_by": body.get("_generated_by", "template"),
        "provider_attempts": provider_attempts,
        "retrieval_used": index_retrieval_used,
        "retrieved_chunks": public_chunks,
        "retrieval": retrieval,
        "prerequisite_title": prerequisite_title,
        "sequence_order": sequence_order,
        # Phase 5 validation
        **{k: report.get(k) for k in (
            "groundedness", "faithfulness", "hallucination_risk", "semantic_similarity",
            "topic_alignment", "trust_score", "trust_band", "trust_components", "trust_weights",
            "flagged_sentences", "verdict_counts", "similarity_method", "block_scores",
        )},
        "validation_available": report.get("available", False),
        "validation_note": report.get("reason"),
        # Phase 4 XAI
        "attribution": xai.attribute_sources(chunks if index_retrieval_used else []),
        "shap": analysis["shap"],
        "evidence_trace": analysis["trace"],
        "context_relevance": analysis["relevance"],
        "excluded_scaffold_blocks": sum(1 for b in (body.get("blocks") or []) if b.get("scaffold")),
        "optimization": optimization,
    }
    return body, explainability
