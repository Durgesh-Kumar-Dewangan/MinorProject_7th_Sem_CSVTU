# embeds text + stores it in a faiss index (one index per subject) so we can do
# real RAG - find the most relevant bits of the uploaded syllabus for a given
# topic instead of just chopping the first N chars off the raw text.
#
# using all-MiniLM-L6-v2, it's small (~80mb) and runs fine on cpu. tried bge-m3
# first but it's way bigger and slower, not worth it for "install and it just works"
#
# chunks get tagged with topic_id but retrieval right now just ranks by
# similarity to the query, doesn't filter by topic - stuff from other topics
# just naturally scores lower and drops out of top-k
import os
import pickle
from typing import Any, Dict, List, Optional
import numpy as np

# not importing faiss / sentence_transformers up top on purpose - they're both
# pretty big optional deps, if only one is installed (or neither) this file
# should still import fine. same pattern as ocr.py / image_lookup.py
# or missing install here degrades gracefully instead of crashing anything
# that merely imports this file.

def default_index_dir() -> str:
    """Where the per-subject indexes live, from settings (FAISS_INDEX_DIR).

    Read per call rather than captured as a default argument value, so the
    test suite can redirect it with an env var and callers that pass an
    explicit base_dir still win.
    """
    from app.core.config import get_settings

    return get_settings().FAISS_INDEX_DIR


_model = None  # lazily-loaded SentenceTransformer instance
_model_failed = None  # the exception from a previous failed load, if any
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_DIM = 384  # all-MiniLM-L6-v2 output dimension

class EmbeddingModelUnavailable(RuntimeError):
    """The embedding model can't be loaded here (not installed, or no network
    to download it on first use). Every caller already treats a raise as
    "degrade to keyword-only retrieval"."""

def get_embedding_model():
    """The shared SentenceTransformer, loaded on first use.

    Both the success AND the failure are cached. Without latching the
    failure, a machine that can't reach the model host re-attempts the
    download on *every* embed call - and that attempt is not cheap: the
    underlying client retries with exponential backoff, which measured at
    ~90 seconds per attempt. Since embeddings are hit at upload (chunk
    ingestion) and again on every topic's retrieval + validation, that
    turned one unreachable host into minutes of delay per lesson instead of
    an instant, clean fallback to keyword-only retrieval. similarity.py has
    always latched its own failure this way; this is the same idea one layer
    down, where the actual loading happens.
    """
    global _model, _model_failed
    if _model is not None:
        return _model
    if _model_failed is not None:
        raise EmbeddingModelUnavailable(str(_model_failed)) from _model_failed
    try:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(MODEL_NAME)
    except Exception as exc:   # ImportError, network/SSL failure, corrupt cache...
        _model_failed = exc
        raise EmbeddingModelUnavailable(str(exc)) from exc
    return _model

def reset_model_state() -> None:
    """Test hook: forget a cached load FAILURE so the next call retries.

    Deliberately keeps an already-loaded model: that's a pure cache with no
    bearing on test outcomes, and dropping it would make the next test that
    needs real embeddings reload the model from scratch.
    """
    global _model_failed
    _model_failed = None

def embed_texts(texts: List[str]) -> np.ndarray:
    model = get_embedding_model()
    embeddings = model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=False,
        convert_to_numpy=True,
    )
    return embeddings.astype("float32")

class SubjectFAISSIndex:
    """One FAISS index + metadata store per subject_id.

    Metadata is the source of truth for chunk TEXT (so keyword/BM25 retrieval
    in retrieval.py works even when no embedding model is available);
    the FAISS index only holds vectors for the entries that could be
    embedded. Each entry carries a `vec_id` pointing at its FAISS row (or
    None if it was stored without a vector). Indexes written before this
    field existed are parallel to the vectors, so position == vec_id.
    """

    def __init__(self, subject_id: str, base_dir: Optional[str] = None):
        self.subject_id = subject_id
        self.dir = os.path.join(base_dir or default_index_dir(), subject_id)
        os.makedirs(self.dir, exist_ok=True)
        self.index_path = os.path.join(self.dir, "index.faiss")
        self.meta_path = os.path.join(self.dir, "metadata.pkl")
        self.dimension = EMBED_DIM

        self.index = None  # None when faiss isn't installed -> keyword-only
        self.metadata: List[Dict[str, Any]] = []

        self._load()

    def _load(self):
        try:
            import faiss
        except Exception:
            faiss = None

        if os.path.exists(self.meta_path):
            with open(self.meta_path, "rb") as f:
                self.metadata = pickle.load(f)
        if faiss is None:
            return
        if os.path.exists(self.index_path):
            self.index = faiss.read_index(self.index_path)
        else:
            # Inner product = cosine when vectors are normalized
            self.index = faiss.IndexFlatIP(self.dimension)

    def save(self):
        if self.index is not None:
            import faiss

            faiss.write_index(self.index, self.index_path)
        with open(self.meta_path, "wb") as f:
            pickle.dump(self.metadata, f)

    def _vec_id(self, position: int, entry: Dict[str, Any]):
        return entry["vec_id"] if "vec_id" in entry else position

    def add_chunks(self, chunks: List[Dict[str, Any]]):
        """
        chunks = [
          {"text": "...", "topic_id": "CS101-U1-T1", "source": "optional"},
          ...
        ]
        Always stores the text (keyword retrieval); stores vectors too when
        faiss + an embedding model are available.
        """
        if not chunks:
            return

        texts = [c["text"] for c in chunks]
        embeddings = None
        if self.index is not None:
            try:
                embeddings = embed_texts(texts)
            except Exception:
                embeddings = None  # no embedding model -> text-only entries

        base = self.index.ntotal if (self.index is not None and embeddings is not None) else 0
        if embeddings is not None:
            self.index.add(embeddings)
        for i, c in enumerate(chunks):
            self.metadata.append({
                "text": c["text"],
                "topic_id": c["topic_id"],
                "source": c.get("source", ""),
                "subject_id": self.subject_id,
                "vec_id": (base + i) if embeddings is not None else None,
            })
        self.save()

    def has_vectors(self) -> bool:
        return self.index is not None and self.index.ntotal > 0

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Vector search. Raises if the embedding model is unavailable."""
        if not self.has_vectors():
            return []

        q_emb = embed_texts([query])
        scores, indices = self.index.search(q_emb, min(top_k, self.index.ntotal))

        by_vec = {}
        for pos, m in enumerate(self.metadata):
            vid = self._vec_id(pos, m)
            if vid is not None:
                by_vec[vid] = (pos, m)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or int(idx) not in by_vec:
                continue
            pos, m = by_vec[int(idx)]
            meta = m.copy()
            meta["chunk_pos"] = pos
            meta["score"] = float(score)
            results.append(meta)
        return results

def chunk_text(text: str, chunk_size: int = 400, overlap: int = 50) -> List[str]:
    # splits on blank lines first since syllabus text is naturally paragraph-shaped,
    # then glues short paragraphs together up to chunk_size. only falls back to
    # dumb character splitting if one single paragraph is longer than chunk_size
    # by itself. point is to not cut a chunk mid-topic - a chunk mixing two
    # different topics scores worse for both when we search against it later
    if not text:
        return []

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [text.strip()] if text.strip() else []

    chunks: List[str] = []
    current = ""

    def flush_current():
        if current.strip():
            chunks.append(current.strip())

    for para in paragraphs:
        if len(para) > chunk_size:
            # single paragraph too big on its own, flush what we have and just
            # chop this one up by character count
            flush_current()
            current = ""
            start = 0
            while start < len(para):
                end = start + chunk_size
                piece = para[start:end].strip()
                if piece:
                    chunks.append(piece)
                start = end - overlap
                if start < 0:
                    start = 0
                if end >= len(para):
                    break
            continue

        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) <= chunk_size:
            current = candidate
        else:
            flush_current()
            current = para

    flush_current()
    return [c for c in chunks if len(c) > 20]

def ingest_document_for_topic(
    subject_id: str,
    topic_id: str,
    document_text: str,
    source: str = "manual",
    base_dir: Optional[str] = None,
) -> int:
    # doc -> chunks -> embed -> stick in faiss, tagged with topic_id
    # returns how many chunks got added
    chunks_text = chunk_text(document_text)
    chunks = [
        {"text": t, "topic_id": topic_id, "source": source}
        for t in chunks_text
    ]
    index = SubjectFAISSIndex(subject_id, base_dir=base_dir)
    index.add_chunks(chunks)
    return len(chunks)


def retrieve_context_for_topic(
    subject_id: str,
    query: str,
    top_k: int = 4,
    base_dir: Optional[str] = None,
) -> List[str]:
    # actual rag retrieval - embed the query (usually topic title + unit name)
    # and grab the top_k closest chunks from that subject's syllabus text.
    # empty list if there's no index yet / nothing ingested, caller should
    # just treat that as "no retrieval, use the fallback" not an error
    index = SubjectFAISSIndex(subject_id, base_dir=base_dir)
    results = index.search(query, top_k=top_k)
    return [r["text"] for r in results]

def retrieve_context_with_meta(
    subject_id: str,
    query: str,
    top_k: int = 4,
    base_dir: Optional[str] = None,
) -> List[Dict[str, Any]]:
    # same as retrieve_context_for_topic but keeps the full metadata (source,
    # score, which topic it was tagged under) instead of just the text.
    # this is what feeds the explainability panel - so someone can actually
    # see which chunk of which document a lesson pulled from
    index = SubjectFAISSIndex(subject_id, base_dir=base_dir)
    return index.search(query, top_k=top_k)
