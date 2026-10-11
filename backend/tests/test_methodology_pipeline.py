"""
Tests for the project methodology phases (see backend/METHODOLOGY.md):
Phase 2 hybrid retrieval, Phase 3 response optimization, Phase 4 XAI
(Shapley/SHAP, evidence trace, relevance), Phase 5 validation + trust score.

Embeddings are faked (hashed bag-of-words) or disabled so the suite runs
offline - the real MiniLM model needs a network download on first use.
"""
import itertools
import math
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.services import embeddings, rag_pipeline, retrieval, similarity, validation, xai

CS_TEXT = (
    "Stacks are linear data structures that follow the last in first out principle. "
    "Push adds an element to the top of the stack and pop removes the top element.\n\n"
    "Queues follow the first in first out principle. Enqueue adds an element at the rear "
    "and dequeue removes the element at the front of the queue.\n\n"
    "Arrays store elements in contiguous memory locations and allow constant time indexing.\n\n"
    "Photosynthesis converts light energy into chemical energy inside chloroplasts."
)


def _fake_embed(texts):
    vecs = []
    for t in texts:
        v = np.zeros(384, dtype="float32")
        for w in similarity.tokenize(t):
            v[hash(w) % 384] += 1.0
        n = np.linalg.norm(v)
        vecs.append(v / n if n else v)
    return np.array(vecs, dtype="float32")


@pytest.fixture()
def no_embeddings(monkeypatch):
    def boom(texts):
        raise OSError("no embedding model in this environment")

    monkeypatch.setattr(embeddings, "embed_texts", boom)
    similarity.reset_embedding_state()
    yield
    similarity.reset_embedding_state()


@pytest.fixture()
def fake_embeddings(monkeypatch):
    monkeypatch.setattr(embeddings, "embed_texts", _fake_embed)
    similarity.reset_embedding_state()
    yield
    similarity.reset_embedding_state()


# ---------------- Phase 2: retrieval ----------------

def test_bm25_ranks_relevant_document_first():
    docs = ["stacks push and pop elements", "photosynthesis in plants", "queues enqueue dequeue"]
    scores = retrieval.BM25(docs).scores("stack push pop")
    assert scores.index(max(scores)) == 0


def test_rrf_rewards_agreement_between_retrievers():
    fused = retrieval.reciprocal_rank_fusion([[1, 2, 3], [3, 1, 4]])
    assert fused[1] > fused[2] and fused[3] > fused[4]
    assert max(fused, key=fused.get) in (1, 3)


def test_select_context_drops_near_duplicates_and_respects_top_k():
    ranked = [
        {"text": "stacks use push and pop on the top element"},
        {"text": "stacks use push and pop on the top element!"},
        {"text": "queues use enqueue and dequeue at both ends"},
        {"text": "arrays give constant time indexing of elements"},
    ]
    chosen = retrieval.select_context(ranked, top_k=3)
    assert len(chosen) == 3
    assert sum("stacks" in c["text"] for c in chosen) == 1


def test_keyword_only_retrieval_when_no_embedding_model(tmp_path, no_embeddings):
    n = embeddings.ingest_document_for_topic("CS1", "syllabus-source", CS_TEXT, source="s.txt", base_dir=str(tmp_path))
    assert n >= 1
    chunks, trace = retrieval.hybrid_retrieve("CS1", "stack push pop", top_k=2, base_dir=str(tmp_path))
    assert chunks and "stack" in chunks[0]["text"].lower()
    assert trace["method"] == "keyword-only"
    assert trace["vector_used"] is False and trace["keyword_used"] is True
    assert chunks[0]["vector_score"] is None


def test_hybrid_retrieval_uses_both_retrievers(tmp_path, fake_embeddings):
    embeddings.ingest_document_for_topic("CS2", "syllabus-source", CS_TEXT, source="s.txt", base_dir=str(tmp_path))
    chunks, trace = retrieval.hybrid_retrieve("CS2", "queue enqueue dequeue", top_k=2, base_dir=str(tmp_path))
    assert trace["method"] == "hybrid"
    assert trace["vector_used"] and trace["keyword_used"] and trace["reranked"]
    assert "queue" in chunks[0]["text"].lower()
    assert chunks[0]["vector_score"] is not None and chunks[0]["rank"] == 1
    assert 0.0 <= chunks[0]["score"] <= 1.0


def test_empty_index_returns_nothing(tmp_path):
    chunks, trace = retrieval.hybrid_retrieve("NOPE", "anything", base_dir=str(tmp_path))
    assert chunks == [] and trace["method"] == "none"


# ---------------- Phase 4: Shapley / SHAP ----------------

def test_shapley_efficiency_symmetry_and_dummy():
    rng = np.random.default_rng(0)
    sim = rng.random((6, 4)).astype("float32")
    sim[:, 3] = sim[:, 2]           # chunk 3 is a copy of chunk 2  -> equal values
    sim2 = np.hstack([sim, np.zeros((6, 1), dtype="float32")])  # dummy chunk that never helps
    phi = xai.shapley_values(sim2)
    total = float(sim2.max(axis=1).mean())
    assert math.isclose(sum(phi), total, rel_tol=1e-6)           # efficiency
    assert math.isclose(phi[2], phi[3], rel_tol=1e-6)            # symmetry
    assert abs(phi[4]) < 1e-9                                    # dummy player
    assert all(p >= -1e-9 for p in phi)                          # monotone value => non-negative


def test_shapley_matches_brute_force_definition():
    rng = np.random.default_rng(1)
    sim = rng.random((5, 3))
    n = 3
    v = lambda cols: float(sim[:, list(cols)].max(axis=1).mean()) if cols else 0.0
    expected = []
    for i in range(n):
        others = [j for j in range(n) if j != i]
        tot = 0.0
        for r in range(n):
            for S in itertools.combinations(others, r):
                w = math.factorial(r) * math.factorial(n - r - 1) / math.factorial(n)
                tot += w * (v(S + (i,)) - v(S))
        expected.append(tot)
    assert np.allclose(xai.shapley_values(sim), expected)


def test_shapley_sampling_path_for_many_chunks():
    sim = np.random.default_rng(2).random((4, xai.EXACT_LIMIT + 2))
    phi = xai.shapley_values(sim)
    assert len(phi) == xai.EXACT_LIMIT + 2
    assert math.isclose(sum(phi), float(sim.max(axis=1).mean()), rel_tol=1e-6)


# ---------------- Phase 5: validation ----------------

CHUNKS = [
    {"text": "Stacks follow the last in first out principle. Push adds an element to the top and pop removes it.",
     "source": "notes.txt", "score": 0.8},
    {"text": "Queues follow first in first out order using enqueue and dequeue.", "source": "notes.txt", "score": 0.5},
]
GROUNDED = [{"title": "Stacks", "body": "Stacks follow the last in first out principle. Push adds an element to the top of the stack. Pop removes the top element."}]
OFFTOPIC = [{"title": "Whales", "body": "Blue whales migrate across oceans every winter season. They feed on krill near polar regions. Their songs travel hundreds of kilometres."}]


def test_grounded_lesson_beats_off_topic_lesson(no_embeddings):
    good = validation.validate_response(validation.build_evidence(GROUNDED, CHUNKS), "stacks")
    bad = validation.validate_response(validation.build_evidence(OFFTOPIC, CHUNKS), "stacks")
    assert good["similarity_method"] == "lexical"
    assert good["groundedness"] > bad["groundedness"]
    assert good["faithfulness"] > bad["faithfulness"]
    assert good["hallucination_risk"] < bad["hallucination_risk"]
    assert good["trust_score"] > bad["trust_score"]
    assert good["trust_band"] in ("high", "medium") and bad["trust_band"] == "low"
    assert bad["flagged_sentences"], "unsupported sentences must be surfaced"
    for k in ("groundedness", "faithfulness", "hallucination_risk", "semantic_similarity", "trust_score"):
        assert 0.0 <= good[k] <= 1.0 and 0.0 <= bad[k] <= 1.0


def test_number_not_in_evidence_downgrades_a_supported_sentence(no_embeddings):
    blocks = [{"title": "Stacks", "body": "Stacks follow the last in first out principle and hold exactly 4096 elements."}]
    ev = validation.build_evidence(blocks, CHUNKS)
    v = validation.verify_evidence(ev)[0]
    assert v["verdict"] != "supported"
    assert any("4096" in r for r in v["reasons"])


def test_trust_weights_sum_to_one():
    assert math.isclose(sum(validation.TRUST_WEIGHTS.values()), 1.0)


def test_no_evidence_gives_no_score_not_a_fake_zero():
    r = validation.validate_response(validation.build_evidence(GROUNDED, []))
    assert r["available"] is False and r["trust_score"] is None and r["groundedness"] is None


def test_evidence_trace_links_sentences_to_sources(no_embeddings):
    ev = validation.build_evidence(GROUNDED, CHUNKS)
    trace = xai.evidence_trace(ev, validation.verify_evidence(ev))
    assert trace and trace[0]["source"] == "notes.txt" and trace[0]["chunk_index"] == 0
    rel = xai.context_relevance(ev, CHUNKS, xai.shapley_attribution(ev), validation.verify_evidence(ev))
    assert rel[0]["sentences_supported"] >= 1 and rel[0]["shap_share"] is not None


def test_attribute_sources_weights_sum_to_one():
    a = xai.attribute_sources(CHUNKS + [{"text": "x", "source": "ref.pdf", "score": 0.7}])
    assert math.isclose(sum(r["weight"] for r in a), 1.0, abs_tol=0.01)
    assert xai.attribute_sources([]) == []


# ---------------- Phase 3: response optimization + pipeline ----------------

def test_optimize_response_cleans_blocks_and_quiz():
    body = {
        "blocks": [
            {"title": "A", "body": "  a real explanation that is long enough  "},
            {"title": "a", "body": "duplicate title should be dropped entirely"},
            {"title": "B", "body": "short"},
        ],
        "quiz": [{"q": "?", "options": ["x", "y"], "answer": 9}, {"q": "?", "options": ["only"], "answer": 0}],
    }
    out, notes = rag_pipeline.optimize_response(body)
    assert [b["title"] for b in out["blocks"]] == ["A"]
    assert out["quiz"] == [{"q": "?", "options": ["x", "y"], "answer": 0}]
    assert len(notes) >= 3


def _body(blocks):
    return {"blocks": blocks, "quiz": [], "arrange": [], "fill": [], "catch": [], "notes": [], "_generated_by": "fake-llm"}


def _run(generate, tmp_path, monkeypatch):
    # chdir so the index dir (FAISS_INDEX_DIR, a relative path) lands in
    # this test's tmp_path. Ingest with the DEFAULT base_dir rather than a
    # hardcoded "./faiss_indexes": run_topic_pipeline retrieves through the
    # configured default, so hardcoding one side made the two disagree.
    monkeypatch.chdir(tmp_path)
    embeddings.ingest_document_for_topic("CS9", "syllabus-source", CS_TEXT, source="s.txt")
    return rag_pipeline.run_topic_pipeline(
        topic_title="Stacks", unit_title="Data Structures", subject_title="CS", prerequisite_title=None,
        sequence_order=1, raw_text=CS_TEXT, subject_id="CS9", generate=generate,
        template=lambda chunks: {**_body([{"title": "T", "body": "Template explanation about stacks and push pop."}]),
                          "_generated_by": "template"},
    )


def test_pipeline_report_has_every_phase_field(tmp_path, monkeypatch, no_embeddings):
    body, x = _run(lambda **kw: _body(GROUNDED), tmp_path, monkeypatch)
    assert x["retrieval_used"] and x["retrieval"]["method"] == "keyword-only"
    assert x["generated_by"] == "fake-llm"
    for k in ("groundedness", "faithfulness", "hallucination_risk", "semantic_similarity", "trust_score",
              "trust_band", "shap", "evidence_trace", "context_relevance", "attribution", "optimization"):
        assert k in x and x[k] is not None, k
    assert x["shap"]["available"] and x["shap"]["method"] == "shapley-exact"
    assert math.isclose(sum(v["value"] for v in x["shap"]["values"]), x["shap"]["total_groundedness"], abs_tol=1e-3)


def test_low_trust_llm_output_triggers_one_strict_regeneration(tmp_path, monkeypatch, no_embeddings):
    calls = []

    def gen(**kw):
        calls.append(kw.get("strict", False))
        return _body(GROUNDED if kw.get("strict") else OFFTOPIC)

    body, x = _run(gen, tmp_path, monkeypatch)
    assert calls == [False, True]
    assert x["optimization"]["regenerated"] and x["optimization"]["kept"] == "strict-regeneration"
    assert x["optimization"]["trust_after"] > x["optimization"]["trust_before"]
    assert body["blocks"][0]["title"] == "Stacks"


def test_template_fallback_still_validated_against_excerpt(tmp_path, monkeypatch, no_embeddings):
    body, x = _run(lambda **kw: None, tmp_path, monkeypatch)
    assert x["generated_by"] == "template" and x["trust_score"] is not None
    assert x["optimization"]["regenerated"] is False


# ---------------- end to end over HTTP ----------------

def test_explainability_endpoint_exposes_trust_report(db_session, uploads_dir, tmp_path, monkeypatch, no_embeddings):
    # chdir so the relative UPLOAD_DIR / FAISS_INDEX_DIR land under tmp_path
    # instead of in the repo. The directory is named from the setting rather
    # than hardcoded as "uploads", so it can't drift out of sync with it -
    # the endpoint writes the uploaded file there and 500s if it's missing.
    from app.core.config import get_settings

    monkeypatch.chdir(tmp_path)
    (tmp_path / get_settings().UPLOAD_DIR.lstrip("./")).mkdir(exist_ok=True)
    syllabus = tmp_path / "syl.txt"
    syllabus.write_text(
        "Computer Science 101\n\nUnit 1: Data Structures\nTopic: Stacks and Queues\nTopic: Arrays and Lists\n\n" + CS_TEXT
    )
    client = TestClient(__import__("app.main", fromlist=["app"]).app)
    with open(syllabus, "rb") as f:
        job = client.post("/syllabus/upload", files={"file": ("syl.txt", f, "text/plain")}).json()["jobId"]
    for _ in range(50):
        body = client.get(f"/jobs/{job}").json()
        if body["status"] == "done":
            break
        time.sleep(0.2)
    assert body["status"] == "done"
    topic_id = body["subjects"][0]["units"][0]["topics"][0]["id"]
    x = client.get(f"/topics/{topic_id}/explainability").json()
    assert x["available"] is True
    assert x["trust_band"] in ("high", "medium", "low") and 0 <= x["trust_score"] <= 1
    assert x["shap"]["available"] and x["evidence_trace"] and x["context_relevance"]
    assert x["retrieval"]["method"] in ("keyword-only", "hybrid", "excerpt-fallback")


# ---------------- Phase 1: multimodal ingestion ----------------

@pytest.fixture()
def multimodal_pdf(tmp_path):
    from PIL import Image, ImageDraw
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.platypus import Table, TableStyle

    chart = Image.new("RGB", (400, 260), "white")
    d = ImageDraw.Draw(chart)
    for i, (h, col) in enumerate([(80, "blue"), (150, "blue"), (110, "red")]):
        d.rectangle([40 + i * 110, 230 - h, 120 + i * 110, 230], fill=col)
    png = tmp_path / "chart.png"
    chart.save(png)

    pdf = tmp_path / "doc.pdf"
    c = canvas.Canvas(str(pdf), pagesize=A4)
    c.setFont("Helvetica", 12)
    c.drawString(60, 790, "Data Structures course overview. This document explains stacks, queues and arrays in depth.")
    c.drawString(60, 770, "The grading scheme and the weekly hours for each unit are summarised in the table below.")
    t = Table([["Unit", "Topic", "Hours"], ["1", "Arrays", "4"], ["2", "Stacks", "6"]])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.8, colors.black)]))
    t.wrapOn(c, 400, 200)
    t.drawOn(c, 60, 650)
    c.drawImage(str(png), 60, 380, width=300, height=195)
    c.save()
    return str(pdf)


def test_pdf_tables_become_structured_text(multimodal_pdf):
    from app.services import multimodal

    tables = multimodal.extract_tables(multimodal_pdf)
    assert tables and "Topic = Arrays" in tables[0]["text"] and "Hours = 6" in tables[0]["text"]


def test_pdf_images_are_classified_and_described(multimodal_pdf):
    from app.services import multimodal

    imgs = multimodal.extract_images(multimodal_pdf)
    assert len(imgs) == 1
    assert imgs[0]["type"] == "chart or diagram"
    assert imgs[0]["caption"] is None                      # BLIP not installed here -> no fake caption
    assert "Figure (page 1)" in imgs[0]["text"] and "blue" in imgs[0]["text"]


def test_image_type_heuristic_distinguishes_photo_from_chart():
    import numpy as np
    from PIL import Image
    from app.services import multimodal

    noise = Image.fromarray(np.random.default_rng(0).integers(0, 255, (200, 200, 3), dtype="uint8"))
    assert multimodal.analyse_image(noise)["type"] == "photograph"
    assert multimodal.analyse_image(Image.new("RGB", (30, 30), "red"))["type"] == "icon or logo"
    from PIL import ImageDraw
    page = Image.new("RGB", (300, 400), "white")
    d = ImageDraw.Draw(page)
    for y in range(20, 380, 18):
        d.line([(20, y), (270, y)], fill=(30, 30, 30), width=2)
    assert multimodal.analyse_image(page)["type"] == "scanned text or screenshot"


def test_full_extraction_keeps_text_and_appends_tables_and_figures(multimodal_pdf):
    from app.services.multimodal import APPENDIX_MARKER, modality_of
    from app.services.ocr import extract_text_from_file

    text = extract_text_from_file(multimodal_pdf, "pdf")
    assert "Data Structures course overview" in text
    assert APPENDIX_MARKER in text and "Row 1:" in text and "Figure (page 1)" in text
    assert modality_of("Table (page 1), columns: Unit.\nRow 1: Unit = 1.") == "table"
    assert modality_of("Figure (page 2): a chart") == "figure" and modality_of("plain prose") == "text"


# ---------------- template mode uses (and is judged against) real evidence ----------------

def test_extracted_evidence_sentences_are_verbatim_and_on_topic():
    ex = rag_pipeline.extract_evidence_sentences("Stacks", CHUNKS)
    assert ex and all(any(s in c["text"] for c in CHUNKS) for s in ex["sentences"])   # verbatim
    assert any("Stacks" in s for s in ex["sentences"]) and ex["sources"] == ["notes.txt"]
    assert rag_pipeline.extract_evidence_sentences("Quantum Chromodynamics", CHUNKS) is None


def test_scaffold_blocks_are_not_validated(no_embeddings):
    blocks = [
        {"title": "Filler", "body": "This topic is one of several topics in this unit and you should study it well.", "scaffold": True},
        {"title": "From your material", "body": "Stacks follow the last in first out principle."},
    ]
    ev = validation.build_evidence(blocks, CHUNKS)
    assert [s["block_title"] for s in ev.sentences] == ["From your material"]


def test_template_with_evidence_is_grounded_and_without_is_honestly_unvalidated(tmp_path, monkeypatch, no_embeddings):
    from app.api.routers import syllabus as syl

    def template_for(title):
        topic = type("T", (), {"id": 1, "title": title, "topic_id": "CS9-U1-T1",
                               "unit": type("U", (), {"unit_title": "Data Structures"})()})
        return lambda chunks: syl._template_topic_content(topic, None, 1, "CS", evidence_chunks=chunks)

    monkeypatch.chdir(tmp_path)
    embeddings.ingest_document_for_topic("CS9", "syllabus-source", CS_TEXT, source="notes.txt")
    _, x = rag_pipeline.run_topic_pipeline(
        topic_title="Stacks", unit_title="Data Structures", subject_title="CS", prerequisite_title=None, sequence_order=1,
        raw_text=CS_TEXT, subject_id="CS9", generate=lambda **kw: None, template=template_for("Stacks"))
    assert x["generated_by"] == "template" and x["excluded_scaffold_blocks"] >= 3
    assert x["faithfulness"] == 1.0 and x["hallucination_risk"] == 0.0 and x["trust_band"] in ("high", "medium")
    assert x["evidence_trace"] and all(t["verdict"] == "supported" for t in x["evidence_trace"])

    _, y = rag_pipeline.run_topic_pipeline(
        topic_title="Quantum Chromodynamics", unit_title="Physics", subject_title="CS", prerequisite_title=None,
        sequence_order=1, raw_text=CS_TEXT, subject_id="CS9", generate=lambda **kw: None,
        template=template_for("Quantum Chromodynamics"))
    assert y["trust_score"] is None and y["validation_available"] is False
    assert "no claims" in y["validation_note"]


def test_context_relevance_counts_only_supported_sentences(no_embeddings):
    ev = validation.build_evidence(OFFTOPIC, CHUNKS)
    rel = xai.context_relevance(ev, CHUNKS, xai.shapley_attribution(ev), validation.verify_evidence(ev))
    assert sum(r["sentences_supported"] for r in rel) == 0
