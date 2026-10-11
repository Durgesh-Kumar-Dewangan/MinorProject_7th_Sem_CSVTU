"""
Phase 5 - Responsible AI validation.

Every generated lesson sentence is compared with the retrieved evidence
chunks (services/similarity.py picks embedding or lexical similarity and
reports which). From that single evidence matrix we derive:

  groundedness         mean best-evidence similarity over sentences
  faithfulness         share of sentences clearing the support threshold
  hallucination_risk   unsupported sentences (weak ones count half), plus
                       a numeric check: numbers that appear in no evidence
  semantic_similarity  whole lesson vs whole retrieved context, and
                       lesson vs the topic query (topic alignment)
  evidence verification  per-sentence verdict: supported / weak / unsupported
  trust score          weighted composite of the above -> "Final
                       Trustworthy Response" band (high / medium / low)

Honest scope: "unsupported" means *not backed by the retrieved material*.
Lessons are allowed to add general subject knowledge, so an unsupported
sentence is a flag to verify, not a proven falsehood. These are similarity-
based validators, not a trained NLI/fact-checking model.
"""
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np

from app.services.similarity import (
    SUPPORT_THRESHOLD,
    WEAK_THRESHOLD,
    pairwise,
    split_sentences,
)

# calibration: the similarity value considered "fully grounded" per method,
# so a lexical score isn't unfairly penalised against embedding scores when
# composing the trust score
_TARGET = {"embedding": 0.75, "lexical": 0.45}

TRUST_WEIGHTS = {
    "groundedness": 0.30,
    "faithfulness": 0.25,
    "low_hallucination": 0.20,
    "semantic_similarity": 0.15,
    "retrieval_confidence": 0.10,
}
TRUST_BANDS = ((0.70, "high"), (0.45, "medium"), (0.0, "low"))


@dataclass
class Evidence:
    sentences: List[Dict[str, Any]]   # {block_idx, block_title, text}
    chunks: List[Dict[str, Any]]      # retrieved chunks (text, source, score, ...)
    sim: np.ndarray                   # sentences x chunks, in [0,1]
    method: str                       # "embedding" | "lexical"


def build_evidence(blocks: List[Dict[str, Any]], chunks: List[Dict[str, Any]]) -> Optional[Evidence]:
    sentences = []
    for bi, b in enumerate(blocks or []):
        if b.get("scaffold"):        # structural filler that makes no claims about the subject
            continue
        for s in split_sentences(b.get("body", "")):
            sentences.append({"block_idx": bi, "block_title": b.get("title") or "", "text": s})
    texts = [c["text"] for c in (chunks or []) if c.get("text", "").strip()]
    if not sentences or not texts:
        return None
    sim, method = pairwise([s["text"] for s in sentences], texts)
    return Evidence(sentences, [c for c in chunks if c.get("text", "").strip()], sim, method)


def _numbers(text: str) -> List[str]:
    return re.findall(r"\d+(?:\.\d+)?", text)


def verify_evidence(ev: Evidence) -> List[Dict[str, Any]]:
    """Per-sentence evidence verification."""
    thr, weak = SUPPORT_THRESHOLD[ev.method], WEAK_THRESHOLD[ev.method]
    all_evidence = " ".join(c["text"] for c in ev.chunks)
    out = []
    for i, s in enumerate(ev.sentences):
        best_j = int(ev.sim[i].argmax())
        best = float(ev.sim[i, best_j])
        verdict = "supported" if best >= thr else ("weak" if best >= weak else "unsupported")
        reasons = []
        missing = [n for n in _numbers(s["text"]) if n not in all_evidence]
        if missing:
            reasons.append("number(s) not found in evidence: " + ", ".join(missing[:3]))
            if verdict == "supported":
                verdict = "weak"
        out.append({
            "block": s["block_title"],
            "sentence": s["text"][:220],
            "verdict": verdict,
            "similarity": round(best, 3),
            "chunk_index": best_j,
            "reasons": reasons,
        })
    return out


def validate_response(ev: Optional[Evidence], query: str = "", verdicts: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    if ev is None:
        return {
            "available": False,
            "reason": "no retrieved evidence or no generated text to compare",
            "groundedness": None,
            "faithfulness": None,
            "hallucination_risk": None,
            "semantic_similarity": None,
            "topic_alignment": None,
            "trust_score": None,
            "trust_band": None,
            "flagged_sentences": [],
            "verdict_counts": {},
            "block_scores": [],
            "similarity_method": None,
        }

    verdicts = verdicts or verify_evidence(ev)
    best = ev.sim.max(axis=1)
    n = len(best)
    counts = {k: sum(1 for v in verdicts if v["verdict"] == k) for k in ("supported", "weak", "unsupported")}

    groundedness = float(best.mean())
    faithfulness = counts["supported"] / n
    hallucination_risk = (counts["unsupported"] + 0.5 * counts["weak"]) / n

    lesson_text = " ".join(s["text"] for s in ev.sentences)
    context_text = " ".join(c["text"] for c in ev.chunks)
    sem, _ = pairwise([lesson_text], [context_text])
    semantic_similarity = float(sem[0, 0])
    topic_alignment = None
    if query.strip():
        ta, _ = pairwise([lesson_text], [query])
        topic_alignment = float(ta[0, 0])

    retrieval_conf = float(np.mean([min(1.0, max(0.0, c.get("score", 0.0))) for c in ev.chunks]))
    target = _TARGET[ev.method]
    components = {
        "groundedness": min(1.0, groundedness / target),
        "faithfulness": faithfulness,
        "low_hallucination": 1.0 - hallucination_risk,
        "semantic_similarity": min(1.0, semantic_similarity / target),
        "retrieval_confidence": retrieval_conf,
    }
    trust = sum(TRUST_WEIGHTS[k] * components[k] for k in TRUST_WEIGHTS)
    band = next(label for floor, label in TRUST_BANDS if trust >= floor)

    block_scores: Dict[str, List[float]] = {}
    for s, b in zip(ev.sentences, best):
        block_scores.setdefault(s["block_title"], []).append(float(b))

    flagged = [v for v in verdicts if v["verdict"] != "supported"]
    flagged.sort(key=lambda v: v["similarity"])

    return {
        "available": True,
        "similarity_method": ev.method,
        "groundedness": round(groundedness, 3),
        "faithfulness": round(faithfulness, 3),
        "hallucination_risk": round(hallucination_risk, 3),
        "semantic_similarity": round(semantic_similarity, 3),
        "topic_alignment": round(topic_alignment, 3) if topic_alignment is not None else None,
        "trust_score": round(trust, 3),
        "trust_band": band,
        "trust_components": {k: round(v, 3) for k, v in components.items()},
        "trust_weights": TRUST_WEIGHTS,
        "flagged_sentences": flagged[:6],
        "verdict_counts": counts,
        "block_scores": [{"title": t, "support": round(sum(v) / len(v), 3)} for t, v in block_scores.items()],
    }
