# Methodology to code map

The project follows a five-phase trustworthy-RAG methodology. Every topic lesson
runs Phases 2-5 through `app/services/rag_pipeline.py::run_topic_pipeline`;
Phase 1 happens at upload time. The result is a lesson plus a **trust score**
and the evidence behind it ("Final Trustworthy Response"), served by
`GET /topics/{id}/explainability` and rendered by `nsya-frontend/js/xai-metrics.js`.

| Phase | Item | Where | Status |
|---|---|---|---|
| 1 Document processing | Document -> text extraction | `services/ocr.py`, `parser.py` (PyMuPDF, pdfplumber, optional PaddleOCR) | done |
| | Chunking, embeddings, FAISS storage | `services/embeddings.py` (MiniLM + one FAISS index per subject; chunk text is always stored, so keyword search works without vectors) | done |
| | Multimodal: table parsing -> structured text | `services/multimodal.py::extract_tables` (pdfplumber) | done, tested |
| | Multimodal: image extraction, feature detection, image-type classification | `multimodal.py::extract_images / analyse_image` (PyMuPDF + pixel statistics) | done, tested. Type is a **heuristic**, not a trained classifier |
| | Multimodal: BLIP captioning | `multimodal.py::caption_image` | implemented, **optional and not verified here**: needs the BLIP weights, which could not be downloaded in the dev sandbox. Without them figures get a heuristic description, never a fake caption |
| 2 Multi-RAG retrieval | Vector search + keyword search | `services/retrieval.py` (FAISS, own BM25) | done, tested |
| | Combine results | reciprocal rank fusion | done |
| | Re-rank context | lightweight reranker (relevance + fused rank); no cross-encoder | done |
| | Context selection | top-k under a character budget, near-duplicate removal | done |
| 3 LLM generation | Prompt construction | `services/llm_client.py::_prompt_for` (numbered evidence, strict mode) | done |
| | Response generation | providers: ollama (run LLaMA here), gemini, groq, mistral; template fallback | done |
| | Response optimization | `rag_pipeline.optimize_response` + one strict-mode regeneration when trust is low | done, tested with a fake provider (no live LLM available in dev) |
| 4 Explainable AI | Hybrid retrieval system | Phase 2, its trace is part of the report | done |
| | Retrieval attribution | `services/xai.py::attribute_sources` | done |
| | Context relevance scoring | `xai.py::context_relevance` | done |
| | Evidence tracing | `xai.py::evidence_trace` (sentence -> chunk -> source, with modality) | done |
| | SHAP integration | `xai.py::shapley_values` - exact Shapley values over the retrieved evidence chunks | done, property-tested. Native implementation (not the `shap` package); it explains which evidence the lesson's groundedness depends on, not the LLM's weights |
| 5 Responsible AI | Groundedness, faithfulness | `services/validation.py` | done |
| | Hallucination detection | unsupported/weak sentences + numbers absent from the evidence | done. "Unsupported" means not backed by the retrieved material, not proven false |
| | Semantic similarity | lesson vs context, lesson vs topic | done |
| | Evidence verification | per-sentence verdict: supported / weak / unsupported | done |
| | Trust score | weighted composite (weights are returned in the report) | done |

## Similarity backend
`services/similarity.py` uses sentence embeddings when the model loads and falls
back to TF-IDF cosine otherwise. The report says which one was used
(`similarity_method`); thresholds are calibrated per method.

## Template mode (no LLM configured)
The template lesson is structural scaffolding (blocks marked `scaffold`, skipped by
the validators) plus, when evidence exists, a **"From your material"** block of
sentences extracted verbatim from the retrieved chunks. If there is neither
evidence nor an LLM, the trust score is `null` with an explanation, not a made-up number.

## Tests
`cd backend && python -m pytest tests` (65 tests). Tests use their own database file
(`test_suite.db`) and fake/disable the embedding model, so they run offline.
