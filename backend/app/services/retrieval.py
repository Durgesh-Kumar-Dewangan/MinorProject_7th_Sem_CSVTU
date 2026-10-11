"""
Phase 2 - Multi-RAG retrieval.

  1. Query input
  2. Multi retrieval: (a) vector search (FAISS)   (b) keyword search (BM25)
  3. Combine results   - Reciprocal Rank Fusion
  4. Re-rank context   - lightweight reranker (no cross-encoder model):
                         absolute relevance blended with the fused rank
  5. Context selection - top-k under a character budget, dropping
                         near-duplicate chunks

Each stage is recorded in the returned `trace` so Phase 4 (XAI) can show
exactly how the context was produced. If the embedding model or faiss is
unavailable the pipeline degrades to keyword-only and says so.
"""
import math
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from app.services.similarity import tokenize

RRF_K = 60
CONTEXT_CHAR_BUDGET = 3000
DUPLICATE_JACCARD = 0.8


class BM25:
    def __init__(self, docs: List[str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tokens = [tokenize(d) for d in docs]
        self.n = len(docs)
        self.avgdl = (sum(len(t) for t in self.tokens) / self.n) if self.n else 0.0
        self.df: Counter = Counter()
        for toks in self.tokens:
            for t in set(toks):
                self.df[t] += 1

    def scores(self, query: str) -> List[float]:
        q = tokenize(query)
        out = []
        for toks in self.tokens:
            tf = Counter(toks)
            dl = len(toks) or 1
            s = 0.0
            for term in q:
                if term not in tf:
                    continue
                idf = math.log(1 + (self.n - self.df[term] + 0.5) / (self.df[term] + 0.5))
                f = tf[term]
                s += idf * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1)))
            out.append(s)
        return out


def reciprocal_rank_fusion(rankings: List[List[int]], k: int = RRF_K) -> Dict[int, float]:
    fused: Dict[int, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (k + rank)
    return fused


def query_coverage(query: str, text: str) -> float:
    q = set(tokenize(query))
    if not q:
        return 0.0
    return len(q & set(tokenize(text))) / len(q)


def _jaccard(a: str, b: str) -> float:
    ta, tb = set(tokenize(a)), set(tokenize(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def select_context(ranked: List[Dict[str, Any]], top_k: int, char_budget: int = CONTEXT_CHAR_BUDGET) -> List[Dict[str, Any]]:
    chosen: List[Dict[str, Any]] = []
    used = 0
    for cand in ranked:
        if len(chosen) >= top_k:
            break
        if any(_jaccard(cand["text"], c["text"]) >= DUPLICATE_JACCARD for c in chosen):
            continue
        if chosen and used + len(cand["text"]) > char_budget:
            continue
        chosen.append(cand)
        used += len(cand["text"])
    return chosen


def hybrid_retrieve(
    subject_id: str,
    query: str,
    top_k: int = 4,
    candidate_k: int = 12,
    base_dir: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Returns (selected_chunks, trace). Empty list if nothing is indexed."""
    from app.services.embeddings import SubjectFAISSIndex

    trace: Dict[str, Any] = {
        "query": query,
        "vector_used": False,
        "keyword_used": False,
        "candidates": 0,
        "reranked": False,
        "selected": 0,
        "method": "none",
    }
    try:
        index = SubjectFAISSIndex(subject_id, base_dir=base_dir)
    except Exception:
        return [], trace
    docs = index.metadata
    if not docs:
        return [], trace

    # (a) vector search -------------------------------------------------
    vec_score: Dict[int, float] = {}
    vec_rank: List[int] = []
    if index.has_vectors():
        try:
            for hit in index.search(query, top_k=candidate_k):
                vec_score[hit["chunk_pos"]] = hit["score"]
                vec_rank.append(hit["chunk_pos"])
            trace["vector_used"] = bool(vec_rank)
        except Exception:
            trace["vector_used"] = False  # embedding model unavailable -> keyword-only

    # (b) keyword search (BM25) ------------------------------------------
    bm = BM25([m["text"] for m in docs])
    kw_all = bm.scores(query)
    kw_order = sorted((i for i, s in enumerate(kw_all) if s > 0), key=lambda i: kw_all[i], reverse=True)[:candidate_k]
    trace["keyword_used"] = bool(kw_order)

    if not vec_rank and not kw_order:
        return [], trace

    # combine (RRF) --------------------------------------------------------
    rankings = [r for r in (vec_rank, kw_order) if r]
    fused = reciprocal_rank_fusion(rankings)
    max_fused = max(fused.values()) or 1.0
    trace["candidates"] = len(fused)

    # re-rank ---------------------------------------------------------------
    max_bm = max((kw_all[i] for i in kw_order), default=0.0) or 1.0
    candidates = []
    for i, f in fused.items():
        cov = query_coverage(query, docs[i]["text"])
        if i in vec_score:
            relevance = 0.6 * vec_score[i] + 0.4 * cov
        else:
            relevance = cov
        rerank = 0.7 * relevance + 0.3 * (f / max_fused)
        candidates.append({
            "text": docs[i]["text"],
            "source": docs[i].get("source") or "syllabus",
            "topic_id": docs[i].get("topic_id"),
            "score": round(relevance, 3),               # absolute 0..1 relevance shown as "% match"
            "vector_score": round(vec_score[i], 3) if i in vec_score else None,
            "keyword_score": round(kw_all[i] / max_bm, 3) if kw_all[i] > 0 else 0.0,
            "keyword_coverage": round(cov, 3),
            "fused_score": round(f, 4),
            "rerank_score": round(rerank, 4),
        })
    candidates.sort(key=lambda c: c["rerank_score"], reverse=True)
    trace["reranked"] = True

    # context selection ------------------------------------------------------
    selected = select_context(candidates, top_k)
    for rank, c in enumerate(selected, start=1):
        c["rank"] = rank
    trace["selected"] = len(selected)
    trace["method"] = "hybrid" if (trace["vector_used"] and trace["keyword_used"]) else (
        "vector-only" if trace["vector_used"] else "keyword-only"
    )
    return selected, trace


def rank_excerpt(raw_text: str, query: str, top_k: int = 4) -> List[Dict[str, Any]]:
    """
    Fallback when no subject index exists: chunk the raw syllabus text and
    keyword-rank it (BM25) so Phase 3-5 still have real evidence to work
    with. Not counted as "retrieval used" - there is no index involved.
    """
    from app.services.embeddings import chunk_text

    pieces = chunk_text(raw_text or "") or ([raw_text.strip()] if (raw_text or "").strip() else [])
    if not pieces:
        return []
    bm = BM25(pieces)
    scores = bm.scores(query)
    max_bm = max(scores) or 1.0
    order = sorted(range(len(pieces)), key=lambda i: scores[i], reverse=True)
    ranked = []
    for i in order:
        cov = query_coverage(query, pieces[i])
        ranked.append({
            "text": pieces[i],
            "source": "syllabus",
            "topic_id": None,
            "score": round(cov, 3),
            "vector_score": None,
            "keyword_score": round(scores[i] / max_bm, 3) if scores[i] > 0 else 0.0,
            "keyword_coverage": round(cov, 3),
            "fused_score": None,
            "rerank_score": round(scores[i] / max_bm, 4),
        })
    selected = select_context(ranked, top_k)
    for rank, c in enumerate(selected, start=1):
        c["rank"] = rank
    return selected
