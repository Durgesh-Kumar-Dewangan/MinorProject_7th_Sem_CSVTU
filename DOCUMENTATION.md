# NSYA — Explainable AI Personalized Learning Platform

Turns an uploaded syllabus (PDF, image, or text) into an interactive, subject →
unit → topic learning path, with lessons and quizzes generated against your
own material through a retrieval-augmented pipeline, and every lesson backed
by a visible trust score and explainability report instead of an opaque
answer.

**Stack:** FastAPI + SQLite backend, vanilla-JS (no build step) frontend.
No account/login system — single-user, local-first by default.

---

## 1. How a syllabus becomes a lesson

```
Upload (PDF / image / text)
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ PHASE 1 · Document processing            services/ocr.py,     │
│ text extraction → multimodal (tables,    parser.py,           │
│ figures) → chunking → embeddings → FAISS multimodal.py,       │
│                                           embeddings.py        │
└───────────────────────────────────────────────────────────────┘
        │  (per topic, on first open)
        ▼
┌───────────────────────────────────────────────────────────────┐
│ PHASE 2 · Multi-RAG retrieval             services/retrieval.py│
│ vector search + keyword (BM25) → combine  (hybrid_retrieve)    │
│ (reciprocal rank fusion) → re-rank →                           │
│ context selection                                              │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ PHASE 3 · LLM response generation         services/llm_client │
│ prompt construction (numbered evidence)   .py, rag_pipeline.py│
│ → provider call → response optimization                       │
│ → one strict-mode retry if trust is low                       │
└───────────────────────────────────────────────────────────────┘
        │
        ├──────────────────────────────┬──────────────────────────┐
        ▼                              ▼                          │
┌────────────────────────┐   ┌─────────────────────────┐          │
│ PHASE 4 · Explainable AI│   │ PHASE 5 · Responsible AI │          │
│ services/xai.py         │   │ services/validation.py   │          │
│ retrieval attribution,  │   │ groundedness, faithfulness│          │
│ context relevance, SHAP │   │ hallucination risk,       │          │
│ (Shapley values),       │   │ semantic similarity,      │          │
│ evidence tracing        │   │ evidence verification     │          │
└────────────────────────┘   └─────────────────────────┘          │
        │                              │                           │
        └──────────────┬───────────────┘                           │
                        ▼                                          │
              Trust score + band  ◄──────────────────────────────┘
              ("Final Trustworthy Response")
                        │
                        ▼
        Lesson + quiz + exercises, rendered in the UI
        with the trust score and full report one tap away
```

`app/services/rag_pipeline.py::run_topic_pipeline` is the one function that
runs phases 2–5 for a topic. Phase 1 happens once, at upload time.

See **`backend/METHODOLOGY.md`** for the item-by-item mapping of every
methodology bullet point to its code, including what's fully verified versus
what's implemented-but-unverified in this dev environment (BLIP captions,
real LLM providers).

---

## 2. Project structure

```
Minor_project_2026/
├── backend/
│   ├── app/
│   │   ├── main.py                    FastAPI app, CORS, static /uploads mount
│   │   ├── core/config.py             all settings (env vars), see §5
│   │   ├── db/
│   │   │   ├── models.py              User, Syllabus, Unit, Topic, Subtopic,
│   │   │   │                          ReferenceSource — see §6
│   │   │   ├── session.py, base.py
│   │   ├── schemas/syllabus.py        Pydantic response models
│   │   ├── api/routers/
│   │   │   ├── syllabus.py            upload, jobs, topics, subtopics,
│   │   │   │                          explainability, sources, complete
│   │   │   └── knowledge.py           knowledge graph, roadmap, vector search
│   │   └── services/
│   │       ├── parser.py              syllabus text → subjects/units/topics
│   │       ├── ocr.py                 PDF/image text extraction
│   │       ├── multimodal.py          Phase 1: tables → text, images → text
│   │       ├── embeddings.py          chunking, MiniLM embeddings, FAISS index
│   │       ├── similarity.py          embedding OR TF-IDF cosine, auto-fallback
│   │       ├── retrieval.py           Phase 2: hybrid retrieval (BM25 + vector)
│   │       ├── llm_client.py          Phase 3: prompt + provider calls
│   │       ├── rag_pipeline.py        orchestrates phases 2–5 for one topic
│   │       ├── xai.py                 Phase 4: attribution, SHAP, evidence trace
│   │       ├── validation.py          Phase 5: groundedness/faithfulness/trust
│   │       ├── knowledge_graph.py     NetworkX prerequisite graph + roadmap
│   │       └── image_lookup.py        Openverse image search per topic
│   ├── tests/                         65 tests, see §10
│   ├── METHODOLOGY.md                 phase-by-phase code map
│   └── requirements.txt
│
├── nsya-frontend/                     vanilla JS + HTML, no build step
│   ├── index.html
│   ├── css/styles.css
│   └── js/
│       ├── main.js, router.js, shell.js, store.js, api.js
│       ├── screens/                   the 5 rail tabs, see §7
│       │   ├── ingest.js              Upload
│       │   ├── graph.js               Subjects
│       │   ├── arc.js                 Units
│       │   ├── pipeline.js            Topics
│       │   └── profile.js             Profile
│       ├── games/
│       │   ├── theory-reader.js       lesson view + per-topic trust chip/popup
│       │   ├── quiz.js, arrange.js, fill.js, catch.js
│       ├── xai-metrics.js             shared Phase 4/5 report renderer
│       ├── xai-panel.js               per-unit "Explainable AI" drawer
│       └── sources-panel.js           per-subject reference-source upload
│   └── tests/
│       ├── smoke.mjs                  `node tests/smoke.mjs`, see §10
│       └── dom-stub.mjs               minimal DOM so Node can run the modules
│
├── sample-syllabus.txt                single-subject fixture (CS)
├── multi-subject-sample.txt           two-subject fixture (CS + Physics)
├── install.cmd / install.ps1 / install.sh   one-shot installer
├── run.cmd / run.ps1 / run.sh               starts backend + frontend
├── install-ocr.*                            optional OCR extra
└── backend/.env.example                     copied to .env on first install
```

---

## 3. Setup

### One-time install
```bash
# Windows: double-click install.cmd, or from PowerShell: .\install.ps1
# Mac/Linux:
bash install.sh
```
One command installs everything, in this order:

1. **CPU-only PyTorch** first — `sentence-transformers` otherwise pulls a
   CUDA build that drags in NVIDIA libraries on machines with no GPU.
2. **`backend/requirements.txt`** — FastAPI, faiss, spaCy, and the test
   dependencies (`pytest`, `httpx`, `reportlab`).
3. **The spaCy English model** (`en_core_web_sm`).
4. **The MiniLM embedding model** (~80MB), pre-cached so your first upload
   isn't the thing that waits on a download.
5. **`backend/.env`**, copied from `.env.example` if you don't have one.
6. **`backend/uploads/`**.

It then verifies each piece and prints a status table — `[OK]` or
`[DEGRADED]` per feature, so a failure that scrolled past in the log can't
go unnoticed. Steps 3 and 4 need the network and are *optional*: without
them the app still runs (parser falls back to a blank spaCy pipeline,
retrieval falls back to keyword-only BM25), and the status table says so.
Nothing is started — see "Running it" below.

**Optional extras** (commented at the bottom of `requirements.txt`, install
only if you need them):
- `paddlepaddle`, `paddleocr` — OCR for scanned PDFs/images (`install-ocr.sh` / `.cmd`)
- `alembic`, `psycopg2-binary`, `supabase` — Postgres instead of SQLite
- `camelot-py[cv]` — an alternate table extractor
- `transformers` is already pulled in by `sentence-transformers`, so BLIP
  image captions (Phase 1) work automatically if that model can load —
  nothing extra to install for it

### Running it — the one-command way

```bash
# Windows: double-click run.cmd, or from PowerShell: .\run.ps1
# Mac/Linux:
bash run.sh
```
Starts the backend on `:8000` and the frontend on `:5500`, then opens the
browser. On Windows each server gets its own window (close them to stop);
on Mac/Linux both run in the one terminal and `Ctrl+C` stops both.

### Running it manually (two terminals)

**Terminal 1 — backend:**
```bash
cd backend
source .venv/bin/activate          # Windows: .venv\Scripts\Activate.ps1
uvicorn app.main:app --host 127.0.0.1 --port 8000
```
Interactive API docs: `http://127.0.0.1:8000/docs`

**Terminal 2 — frontend:**
```bash
cd nsya-frontend
python -m http.server 5500
```
Open `http://127.0.0.1:5500`. It's pre-pointed at the backend via
`window.NSYA_API_URL` in `index.html`, and port 5500 is in the backend's
default `CORS_ORIGINS`, so this works with no configuration. If you move
either side to a different host/port, change `window.NSYA_API_URL` **and**
`CORS_ORIGINS` in `backend/.env` together — a browser treats `localhost`
and `127.0.0.1` as different origins, so use the spelling that's actually
in your address bar.

Try it with `sample-syllabus.txt` (one subject) or
`multi-subject-sample.txt` (two subjects, Computer Science + Physics).

---

## 4. Enabling real LLM generation (optional)

Without any provider configured, lessons use the built-in template — honest
structural scaffolding plus, when there's retrieved evidence, sentences
copied **verbatim** from it (see §9). Configure any one of these in
`backend/.env` to get real generated lessons instead:

| Provider | Where it runs | Cost | Setup |
|---|---|---|---|
| Ollama | Your machine | Free, offline | Install [ollama.com](https://ollama.com), `ollama pull llama3.2` |
| Mistral | Cloud | Free tier | Key from [console.mistral.ai](https://console.mistral.ai) |
| Groq | Cloud (fast) | Free tier | Key from [console.groq.com](https://console.groq.com) |
| Gemini | Cloud | Free tier | Key from [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |

`LLM_PROVIDER_ORDER` (default `ollama,mistral,groq,gemini`) tries each in
order; the first one that returns a valid response wins. A provider with no
key set, or one that fails, is skipped automatically.

### Groq + Mistral in three steps

1. Put the keys in `backend/.env` (create it from `.env.example` if the
   installer hasn't):
   ```ini
   LLM_PROVIDER_ORDER=groq,mistral
   GROQ_API_KEY=gsk_your_key_here
   GROQ_MODEL=llama-3.1-8b-instant
   MISTRAL_API_KEY=your_mistral_key
   MISTRAL_MODEL=mistral-small-latest
   ```
   Put Groq first if you want speed; Mistral then acts as the fallback when
   Groq rate-limits. `.env` is only read at startup, so **restart the
   backend** after editing it.
2. Upload a syllabus and open any topic.
3. Open the trust chip on the lesson (or the unit's **Explainable AI**
   drawer) and check **"Generated by"**. It should name `groq` or
   `mistral`, not `template`.

**Check the model names against your provider's console.** Hosted models
get retired, and a retired name is rejected per-request — the app can't
know that in advance. If a name is stale you'll see it spelled out (see
below) rather than having to guess.

### Telling "not configured" apart from "configured but broken"

Every provider attempt is recorded and shown in the report as
`provider_attempts`, under **"Which model wrote this"**:

```
[groq   ] HTTP 400: The model `llama-2-70b-chat` has been decommissioned
[mistral] no API key set (MISTRAL_API_KEY)
[gemini ] HTTP 401: API key not valid
```

The lesson still falls back to the template — but a rejected key, a retired
model and "no provider configured" used to be indistinguishable from the
outside, all three reported as *"Built-in template (no LLM configured)"*.

**What is and isn't verified here:** the full request/response path for all
four providers is covered by `tests/test_llm_providers.py` — endpoint URL,
auth header, request body, response parsing, JSON-from-fences extraction,
provider fallback order, and each failure mode above — with
`urllib.request.urlopen` faked. That leaves exactly one unverified step:
the TLS hop to the real host, which needs your key and your network.

---

## 5. Configuration reference (`backend/.env`)

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./sya.db` | Swap for a Postgres URL if desired |
| `UPLOAD_DIR` | `./uploads` | Where uploaded files are stored |
| `FAISS_INDEX_DIR` | `./faiss_indexes` | Per-subject retrieval indexes (the test suite redirects this) |
| `CORS_ORIGINS` | `127.0.0.1`/`localhost` on ports 5500, 5173, 3000, 8080 | Must include your frontend's exact origin |
| `LLM_PROVIDER_ORDER` | `ollama,mistral,groq,gemini` | Try order for Phase 3 |
| `MISTRAL_API_KEY` / `MISTRAL_MODEL` | — / `mistral-small-latest` | |
| `GROQ_API_KEY` / `GROQ_MODEL` | — / `llama-3.1-8b-instant` | |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | — / `gemini-1.5-flash` | |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` | `http://localhost:11434` / `llama3.2` | |
| `PREGENERATE_UNIT_ENTRY_TOPICS` | `true` | Pre-generate each unit's 1st topic on upload |
| `PREGENERATE_NEXT_ON_COMPLETE` | `true` | Pre-generate the next topic when one is completed |
| `PREGENERATE_ALL_TOPICS` | `false` | Generate every topic immediately (real cost — see comment in `config.py`) |
| `BLIP_MODEL` | `Salesforce/blip-image-captioning-base` | Override the image-captioning model |

---

## 6. Data model

```
User ──< Syllabus ──< Unit ──< Topic ──< Subtopic
                        │        │
                        │        └── ReferenceSource is linked by subject_id
                        │            (a string like "CS101"), not a real FK —
                        │            subjects themselves live inside
                        │            Syllabus.curriculum (JSON), not a table
                        └── Syllabus.knowledge_graph (JSON) — the NetworkX
                            prerequisite graph, saved as node_link_data
```

- **`Syllabus`** — one row per upload. `phase` tracks `extract → distribute
  → generate → done` (or `error`). `curriculum` is the parsed subject/unit/
  topic tree as JSON; `raw_text` is the extracted document text (multimodal
  appendix included, see §9).
- **`Topic`** — `topic_id` (e.g. `CS101-U1-T1`) is globally unique.
  `sequence_order` and `prerequisite_topic_id` come from the knowledge
  graph. `generated_content` and `generated_by` cache the lesson so it's
  not regenerated on every visit. `explainability` holds the full Phase
  4/5 report (everything `GET /topics/{id}/explainability` returns).
- **`Subtopic`** — a topic's lesson is broken into these as real rows
  (FK to `Topic`), not a JSON array buried in `generated_content`.
- **`ReferenceSource`** — extra per-subject material (max 2 per subject,
  enforced in the endpoint) that gets chunked into that subject's FAISS
  index alongside the syllabus text.

---

## 7. Frontend: the 5 tabs

`shell.js` defines the rail: **Upload → Subjects → Units → Topics →
Profile**, matching the hash routes in `router.js`:

```
#/ingest                              Upload a syllabus
#/graph                               Subjects (each has an upload badge
                                       to add a reference source directly)
  → #/arc/:subjectId                  That subject's Units (with a
                                       "sources" corner button too)
    → #/pipeline/:subjectId/:unitId   That unit's Topics (with an
                                       "Explainable AI" trigger for the
                                       whole unit)
      → #/learn/:subjectId/:unitId/:topicId
                                       The lesson: theory → quiz → arrange
                                       → fill → catch, with a trust-score
                                       chip that opens the full report
#/profile                             Stats across everything uploaded
```

**`xai-metrics.js`** is the one shared renderer for the Phase 4/5 report —
used by both the per-lesson popup (`theory-reader.js`) and the per-unit
drawer (`xai-panel.js`), so they can't drift out of sync. It draws score
bars for every metric the backend could compute, and an honest "N/A" (never
a fake number) for anything it couldn't.

---

## 8. API reference

All routes are on the backend (no `/api/v1` prefix except the knowledge
router). Full interactive docs at `/docs`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness check |
| POST | `/syllabus/upload` | Upload a file (multipart), returns `{jobId}` (= the syllabus's own id) |
| GET | `/jobs/{job_id}` | Poll upload/processing status; returns the full subject/unit/topic tree once done, each topic carrying its stored `completed` / `accuracy` |
| GET | `/topics/{topic_id}?regenerate=` | Get (or force-regenerate) a topic's lesson — generates on first call |
| GET | `/topics/{topic_id}/subtopics` | Lightweight id/title/order list of a topic's subtopics |
| GET | `/subtopics/{subtopic_id}` | One subtopic's full content + parent context |
| GET | `/topics/{topic_id}/explainability` | The full Phase 4/5 report (generates the topic first if needed) |
| POST | `/topics/{topic_id}/complete` | Record a completion (`accuracy` in the body, clamped to 0-100 and persisted); triggers next-topic pre-gen |
| POST | `/subjects/{subject_id}/sources` | Upload a reference source (multipart), max 2 per subject |
| GET | `/subjects/{subject_id}/sources` | List a subject's reference sources |
| GET | `/` , `/{syllabus_id}` | List / fetch raw syllabus records |
| GET | `/api/v1/knowledge/{syllabus_id}/graph` | The NetworkX knowledge graph, node-link JSON |
| GET | `/api/v1/knowledge/{syllabus_id}/roadmap/{subject_id}` | Topological-sort learning order for one subject |
| POST | `/api/v1/knowledge/ingest` | Manual chunk+embed ingestion into a subject's FAISS index |
| POST | `/api/v1/knowledge/search` | Manual vector search over a subject's index |

### The explainability report shape (`GET /topics/{id}/explainability`)

```jsonc
{
  "available": true,
  "generated_by": "template",              // or ollama / mistral / groq / gemini
  "provider_attempts": [                   // one entry per provider tried
    { "provider": "groq", "outcome": "HTTP 401: Invalid API Key" },
    { "provider": "mistral", "outcome": "ok" }
  ],
  "retrieval_used": true,
  "retrieval": { "method": "hybrid", "vector_used": true, "keyword_used": true,
                 "reranked": true, "candidates": 8, "selected": 4 },
  "retrieved_chunks": [ { "snippet": "...", "source": "...", "score": 0.81 } ],

  // Phase 5 — Responsible AI
  "groundedness": 0.58, "faithfulness": 1.0, "hallucination_risk": 0.0,
  "semantic_similarity": 0.63, "topic_alignment": 0.71,
  "trust_score": 0.98, "trust_band": "high",       // "Final Trustworthy Response"
  "trust_components": { "...": "..." }, "trust_weights": { "...": "..." },
  "verdict_counts": { "supported": 3, "weak": 0, "unsupported": 0 },
  "flagged_sentences": [],
  "similarity_method": "embedding",                 // or "lexical" (TF-IDF fallback)
  "validation_available": true, "validation_note": null,

  // Phase 4 — Explainable AI
  "attribution": [ { "source": "notes.pdf", "weight": 0.6 } ],
  "shap": { "available": true, "method": "shapley-exact",
            "values": [ { "source": "...", "share": 0.4, "snippet": "..." } ] },
  "evidence_trace": [ { "sentence": "...", "verdict": "supported", "source": "..." } ],
  "context_relevance": [ { "source": "...", "modality": "text", "relevance": 0.8 } ],
  "optimization": { "regenerated": false, "notes": [] }
}
```

Any metric that couldn't be computed (no evidence, embedding model
unavailable) is `null` with a `validation_note` explaining why — never a
fabricated number.

---

## 9. What "trustworthy" actually means here

- **Template mode is honest about its limits.** With no LLM configured, the
  template is structural scaffolding (marked `scaffold: true`, skipped by
  the validators) plus, when there's retrieved evidence, a **"From your
  material"** block of sentences copied verbatim from it — faithful by
  construction. With neither an LLM nor evidence, the trust score is `null`
  with a stated reason, not a made-up percentage.
- **"Unsupported" means "not backed by the retrieved material," not
  "false."** A lesson can correctly add general subject knowledge the
  syllabus never wrote down. Hallucination risk flags what to double-check
  against your own material, not proven falsehoods.
- **The similarity backend degrades honestly.** Sentence embeddings when
  the model loads; TF-IDF cosine similarity when it can't (no network, not
  installed). `similarity_method` in every report says which one ran.
- **SHAP here is a native, exact Shapley-value implementation** over the
  retrieved evidence chunks (property-tested: efficiency, symmetry, dummy
  player) — it explains which evidence the lesson's groundedness depends
  on. It is not the `shap` package, and it does not look inside an LLM's
  weights (providers are called over HTTP).
- **Image type classification is a pixel-statistics heuristic** (colour
  variety, edge density, background share), not a trained classifier.

---

## 10. Testing

### Backend (65 tests)

```bash
cd backend
python -m pytest tests
```
`pytest`, `httpx` and `reportlab` are installed by the installer as real
entries in `requirements.txt` — four of these tests build a PDF at runtime
to exercise Phase 1 table/figure extraction, and they used to error at
fixture setup on a stock install.

Tests write only to their own `test_*` locations — `test_suite.db`,
`test_faiss_indexes/` and `test_uploads/` (via `DATABASE_URL`,
`FAISS_INDEX_DIR` and `UPLOAD_DIR`) — so a test run never touches `sya.db`,
`faiss_indexes/` or `uploads/`. That isolation matters: ingestion is keyed
by `subject_id` and the fixtures use real-looking ids like `CS101`, so a
shared index directory meant every run mixed fixture chunks into the
evidence your own lessons are grounded in, and a shared upload directory
left a copy of every fixture syllabus behind. They also
fake or disable the embedding model and stub the Openverse image lookup, so
the whole suite runs offline **and** deterministically — nothing passes or
fails depending on whether the machine happens to have internet.
Coverage includes: syllabus parsing (single/multi-subject), knowledge-graph
sequencing, concurrency dedup, hybrid retrieval (BM25 + fused + re-ranked),
Shapley values (checked against the brute-force definition), the trust
score composite, evidence verification, multimodal table/image extraction,
every provider's HTTP request/response shape and failure modes
(`test_llm_providers.py`, with `urlopen` faked), the grounded-vs-off-topic
trust comparison against a real upload,
and a full upload → generate → explainability → complete round-trip over
real HTTP, including that a recorded completion comes back in the job
snapshot the frontend polls.

### Frontend (13 checks)

```bash
cd nsya-frontend
node tests/smoke.mjs
```
No dependencies, no browser, no build step — it runs the real modules
against a ~200-line DOM stub (`tests/dom-stub.mjs`) and a stubbed
backend, then walks a learner through a whole topic: theory → quiz →
arrange → fill → catch → score → notes → mark complete.

It exists for the class of bug static checking cannot see. `seed` was
passed to all four exercise games from `learn.js` without ever being
declared: valid syntax, so `node --check` and every linter passed, but a
`ReferenceError` the instant a learner left the theory stage — which
silently broke every exercise in the app. Comment that declaration out
and this suite fails on the exact line.

---

## 11. Known limitations

- **Verified against the real services** (Windows 11, Python 3.13, live
  `uvicorn`): the MiniLM embedding model loads and produces real 384-dim
  vectors, so Phase 2 runs as true `hybrid` retrieval (vector + BM25 →
  RRF → re-rank), not the keyword-only fallback; and the Openverse image
  lookup resolves real diagrams, so a lesson can carry an `image`. Both
  were previously listed here as unreachable.
- **Still unverified against the real service:** the TLS hop to
  Ollama/Mistral/Groq/Gemini, and BLIP image captions. Everything up to
  that hop *is* verified — `tests/test_llm_providers.py` fakes
  `urlopen` and checks each provider's endpoint, auth header, request body
  and response parsing, the fallback order, and each failure mode (bad key,
  retired model, unreachable host, non-JSON reply). What needs your machine
  is a key and a network. BLIP needs its weights. Both degrade gracefully
  by design (template lessons, captionless figure descriptions).
- **Hosted model names drift.** `GROQ_MODEL`/`MISTRAL_MODEL`/`GEMINI_MODEL`
  defaults were current when written, but providers retire models. A
  retired name is a per-request rejection, so the app surfaces the
  provider's own message in `provider_attempts` rather than guessing —
  check the name against your provider's console if you see a 400 there.
  `gemini-1.5-flash` in particular is old enough to be worth checking.
- **The trust score needs material to compare against.** It scores
  generated sentences against the text retrieved from *your upload*, so a
  syllabus that is only a list of topic names (`- Variables`) has nothing
  to ground against, and the report correctly returns `trust_score: null`
  with a reason instead of a number. Upload something with real prose in
  it, or add a reference source, to get meaningful scores.
- The spaCy model (`en_core_web_sm`) could not be downloaded here (TLS
  interception on this network), so the parser ran on its built-in
  fallback pipeline for the whole 65-test suite — which is itself useful
  evidence that the degraded path works. `install.cmd` installs the model
  and reports whether it succeeded.
- The per-topic generation lock (dedup under concurrent requests) is
  in-process only — correct for the single-`uvicorn`-process deployment
  this app is built for, not for multiple processes behind a load balancer.
- Image-type classification and the OKLCH-based color-mix rendering some
  earlier iterations touched are heuristics, not trained models — called
  out inline in the UI/report rather than presented as more certain than
  they are.
