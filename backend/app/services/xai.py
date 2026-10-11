"""
Phase 4 - Explainable AI framework.

  hybrid retrieval           -> services/retrieval.py (its trace is embedded
                                in the report as `retrieval`)
  retrieval attribution      attribute_sources(): weight of each source
                             document, from the chunks' relevance scores
  context relevance scoring  context_relevance(): per-chunk relevance,
                             vector/keyword components, rank, and how many
                             generated sentences it is the best evidence for
  evidence tracing           evidence_trace(): generated sentence -> the
                             chunk + source document that supports it best
  SHAP explainability        shapley_attribution(): exact Shapley values of
                             each retrieved chunk for the lesson's
                             groundedness

About the SHAP part: this is a native implementation of exact Shapley values
(not the `shap` package). The "model" being explained is the evidence set:
v(S) = mean over lesson sentences of the best similarity to any chunk in S.
phi_i is chunk i's average marginal contribution over all subsets, so
sum(phi) == v(all chunks) exactly (checked in tests). It explains which
retrieved evidence the lesson's groundedness depends on; it does not look
inside the LLM's weights (the LLM is called over HTTP).
"""
import itertools
import math
import random
from typing import Any, Dict, List, Optional

import numpy as np

from app.services.multimodal import modality_of
from app.services.validation import Evidence

EXACT_LIMIT = 10          # up to 2^10 subsets evaluated exactly
MC_PERMUTATIONS = 400     # beyond that, permutation sampling


def attribute_sources(chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Retrieval attribution: share of grounding per source document."""
    if not chunks:
        return []
    by_source: Dict[str, float] = {}
    for c in chunks:
        src = c.get("source") or "unknown source"
        by_source[src] = by_source.get(src, 0.0) + max(float(c.get("score", 0.0)), 0.0)
    total = sum(by_source.values())
    if total <= 0:
        return [{"source": s, "weight": 0.0} for s in by_source]
    return sorted(
        [{"source": s, "weight": round(v / total, 3)} for s, v in by_source.items()],
        key=lambda r: r["weight"],
        reverse=True,
    )


def _value(sim: np.ndarray, cols: List[int]) -> float:
    if not cols:
        return 0.0
    return float(sim[:, cols].max(axis=1).mean())


def shapley_values(sim: np.ndarray) -> List[float]:
    n = sim.shape[1]
    if n == 0 or sim.shape[0] == 0:
        return []
    if n <= EXACT_LIMIT:
        cache: Dict[tuple, float] = {}

        def v(cols: tuple) -> float:
            if cols not in cache:
                cache[cols] = _value(sim, list(cols))
            return cache[cols]

        phi = [0.0] * n
        fact = math.factorial
        for i in range(n):
            others = [j for j in range(n) if j != i]
            for size in range(n):
                weight = fact(size) * fact(n - size - 1) / fact(n)
                for subset in itertools.combinations(others, size):
                    phi[i] += weight * (v(tuple(sorted(subset + (i,)))) - v(subset))
        return phi

    rng = random.Random(0)
    phi = [0.0] * n
    for _ in range(MC_PERMUTATIONS):
        order = list(range(n))
        rng.shuffle(order)
        cols: List[int] = []
        prev = 0.0
        for i in order:
            cols.append(i)
            cur = _value(sim, cols)
            phi[i] += cur - prev
            prev = cur
    return [p / MC_PERMUTATIONS for p in phi]


def shapley_attribution(ev: Optional[Evidence]) -> Dict[str, Any]:
    if ev is None:
        return {"available": False, "method": "shapley", "values": []}
    phi = shapley_values(ev.sim)
    total = _value(ev.sim, list(range(len(ev.chunks))))
    values = []
    for i, c in enumerate(ev.chunks):
        values.append({
            "chunk_index": i,
            "source": c.get("source") or "syllabus",
            "value": round(phi[i], 4),
            "share": round(phi[i] / total, 3) if total > 0 else 0.0,
            "snippet": c["text"][:140],
        })
    return {
        "available": True,
        "method": "shapley-exact" if len(ev.chunks) <= EXACT_LIMIT else "shapley-sampled",
        "total_groundedness": round(total, 4),
        "values": values,
    }


def evidence_trace(ev: Optional[Evidence], verdicts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Generated sentence -> supporting chunk/source, merged with its verdict."""
    if ev is None:
        return []
    out = []
    for v in verdicts:
        c = ev.chunks[v["chunk_index"]]
        out.append({
            "block": v["block"],
            "sentence": v["sentence"],
            "verdict": v["verdict"],
            "similarity": v["similarity"],
            "reasons": v["reasons"],
            "chunk_index": v["chunk_index"],
            "source": c.get("source") or "syllabus",
            "modality": modality_of(c["text"]),
            "evidence": c["text"][:160],
        })
    return out


def context_relevance(
    ev: Optional[Evidence], chunks: List[Dict[str, Any]], shap: Dict[str, Any], verdicts: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Per-chunk relevance report (retrieval scores + how much the lesson leaned on it)."""
    shares = {v["chunk_index"]: v["share"] for v in shap.get("values", [])}
    best_for: Dict[int, int] = {}   # chunk -> sentences it actually SUPPORTS (verdict == supported)
    for v in verdicts:
        if v["verdict"] == "supported":
            best_for[v["chunk_index"]] = best_for.get(v["chunk_index"], 0) + 1
    out = []
    for i, c in enumerate(chunks):
        out.append({
            "chunk_index": i,
            "source": c.get("source") or "syllabus",
            "modality": modality_of(c["text"]),
            "snippet": c["text"][:160],
            "relevance": c.get("score"),
            "vector_score": c.get("vector_score"),
            "keyword_score": c.get("keyword_score"),
            "keyword_coverage": c.get("keyword_coverage"),
            "rank": c.get("rank", i + 1),
            "sentences_supported": best_for.get(i, 0),
            "shap_share": shares.get(i),
        })
    return out
