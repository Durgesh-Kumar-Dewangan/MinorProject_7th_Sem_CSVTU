"""
Similarity backend shared by Phase 2 (retrieval), Phase 4 (XAI) and
Phase 5 (validation).

Two methods, chosen automatically and always reported back to the caller
so the UI/report never pretends one is the other:

  "embedding" - sentence-transformers cosine similarity (all-MiniLM-L6-v2)
  "lexical"   - TF-IDF cosine over stemmed tokens, pure Python + numpy.
                Used when the embedding model can't be loaded (not
                installed, or no network to download it the first time).

Thresholds differ per method because the two score scales differ: a
paraphrase scores far lower under TF-IDF than under a sentence embedding.
"""
import math
import re
from collections import Counter
from typing import Dict, List, Sequence, Tuple

import numpy as np

_STOPWORDS = frozenset(
    "a an and are as at be been but by can do does for from had has have how if in into is it its "
    "may more most no not of on or other so some such than that the their them then there these "
    "they this those to was we were what when where which who will with would you your also each "
    "many any all one two use used using".split()
)

# support thresholds (sentence counts as "supported" by evidence at/above this)
SUPPORT_THRESHOLD = {"embedding": 0.45, "lexical": 0.22}
# below this a sentence is "strongly unsupported" (counts fully as hallucination risk)
WEAK_THRESHOLD = {"embedding": 0.30, "lexical": 0.10}

_embedding_failed = False  # once loading fails, don't retry (and re-hit the network) on every call


def stem(word: str) -> str:
    for suf in ("ingly", "edly", "ing", "ies", "ed", "es", "ly", "s"):
        if len(word) > len(suf) + 2 and word.endswith(suf):
            return word[: -len(suf)] + ("y" if suf == "ies" else "")
    return word


def tokenize(text: str) -> List[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9']+", (text or "").lower())
    return [stem(w) for w in words if len(w) > 2 and w not in _STOPWORDS]


def split_sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", (text or "").strip())
    return [p.strip() for p in parts if len(p.strip()) > 15]


def _lexical_matrix(a: Sequence[str], b: Sequence[str]) -> np.ndarray:
    docs = [tokenize(t) for t in list(a) + list(b)]
    vocab: Dict[str, int] = {}
    df: Counter = Counter()
    for toks in docs:
        for t in set(toks):
            df[t] += 1
            vocab.setdefault(t, len(vocab))
    n = len(docs)
    if not vocab:
        return np.zeros((len(a), len(b)), dtype="float32")
    vecs = np.zeros((n, len(vocab)), dtype="float32")
    for i, toks in enumerate(docs):
        for t, c in Counter(toks).items():
            idf = math.log((1 + n) / (1 + df[t])) + 1.0
            vecs[i, vocab[t]] = (1 + math.log(c)) * idf
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    vecs = vecs / norms
    return vecs[: len(a)] @ vecs[len(a):].T


def pairwise(a: Sequence[str], b: Sequence[str], prefer_embedding: bool = True) -> Tuple[np.ndarray, str]:
    """Similarity matrix (len(a) x len(b)) in [0,1] plus the method used."""
    global _embedding_failed
    if not a or not b:
        return np.zeros((len(a), len(b)), dtype="float32"), "lexical"
    if prefer_embedding and not _embedding_failed:
        try:
            from app.services.embeddings import embed_texts

            ea, eb = embed_texts(list(a)), embed_texts(list(b))
            return np.clip(ea @ eb.T, 0.0, 1.0), "embedding"
        except Exception:
            _embedding_failed = True
    return np.clip(_lexical_matrix(a, b), 0.0, 1.0), "lexical"


def reset_embedding_state() -> None:
    """Test hook: forget a cached embedding-load failure, here and in the
    embeddings module that does the actual loading."""
    global _embedding_failed
    _embedding_failed = False
    try:
        from app.services.embeddings import reset_model_state

        reset_model_state()
    except Exception:
        pass
