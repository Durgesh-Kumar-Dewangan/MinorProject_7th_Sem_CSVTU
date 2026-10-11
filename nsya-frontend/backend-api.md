# NSYA.AI backend contract

The frontend contains **no mock data**. Every screen is driven by your Python
backend. Point the app at it with:

```
VITE_NSYA_API_URL=http://127.0.0.1:8000
```

All responses are JSON. `snake_case` is accepted only where noted.

---

## 1. `POST /syllabus/upload`

Multipart form with a single field `file`.
Upload progress is streamed to the progress bar by the browser (XHR), so no
extra endpoint is needed for it.

**Response**

```json
{ "jobId": "job_123" }
```

`job_id` is also accepted.

---

## 2. `GET /jobs/{jobId}`

Polled every ~1.2s while the app is open — from the extracting screen *and*
in the background on the graph, unit, pipeline and lesson screens. Anything
you change here (subject names, unit names, topic names, topic status) shows
up live in the UI without a reload.

```json
{
  "status": "running",
  "phase": "extract",
  "progress": 42,
  "subjects": [
    {
      "id": "sub_1",
      "name": "Thermodynamics",
      "units": [
        {
          "id": "u_1",
          "number": 1,
          "name": "Laws of Thermodynamics",
          "topics": [
            { "id": "t_1", "name": "Zeroth law", "status": "generating" }
          ]
        }
      ]
    }
  ],
  "error": null
}
```

- `status`: `pending | running | done | error`
- `phase`: `extract | distribute | generate | done`
- `progress`: 0–100 for the **current** phase
- `subjects`: partial results are welcome — send them as soon as you have
  them. The client **merges** by `id`, so renaming a subject/unit/topic in a
  later poll updates the label in place and keeps the learner's local
  progress (completed flag, accuracy).
- `topic.status` (optional): `pending | generating | ready`. Topics that are
  not `ready` show a spinner in the pipeline.

Keep `id` values stable across polls — they are the merge key.

---

## 3. `GET /topics/{topicId}?regenerate=<bool>`

Returns everything the lesson canvas needs. `regenerate=true` is sent only
by the explicit **New round** action: it bypasses the server-side cache and
produces genuinely fresh content. A normal page load sends no query string
and gets the cached lesson back.

There is no `seed` parameter. Exercise shuffling is purely client-side (one
seed per round, held in `js/screens/learn.js` and passed to each game), so
the server never needs to re-draw exercises just to reorder them.

```json
{
  "status": "ready",
  "blocks": [
    {
      "id": "b_1",
      "title": "Definition",
      "body": "The zeroth law of thermodynamics states that if two systems are each in thermal equilibrium with a third system, they are in thermal equilibrium with each other.",
      "source": "Zemansky & Dittman, Heat and Thermodynamics, ch. 1"
    }
  ],
  "quiz": [
    { "q": "The zeroth law defines…", "options": ["Entropy", "Temperature", "Work"], "answer": 1 }
  ],
  "arrange": [
    {
      "term": "Thermal equilibrium",
      "keywords": ["two", "systems", "no", "net", "heat", "flow"],
      "distractors": ["entropy", "adiabatic"],
      "definition": "Two systems are in thermal equilibrium when there is no net heat flow between them."
    }
  ],
  "fill": [
    {
      "text": "Temperature is the property that is equal for systems in ___ ___.",
      "answers": ["thermal", "equilibrium"],
      "bank": ["thermal", "equilibrium", "entropy", "adiabatic"]
    }
  ],
  "catch": [
    { "term": "Thermal equilibrium", "ok": true },
    { "term": "Photosynthesis", "ok": false }
  ],
  "notes": ["Zeroth law is what makes thermometers meaningful."]
}
```

Field notes:

- `blocks[]` — the readable theory. `body` must be exact, technically correct
  prose taken from the book source; `source` is the citation shown under the
  paragraph.
- `quiz[]` — `answer` is the 0-based index into `options`.
- `arrange[]` — `keywords` is the **correct order**; the client shuffles them
  into floating chips. `distractors` are extra wrong chips.
- `fill[]` — one `___` placeholder per entry in `answers`, in order. `bank`
  must contain every answer plus decoys.
- `catch[]` — tap-the-right-terms game. `recall` is accepted as an alias.
- `status` (optional) — `pending | generating | ready`. If it is not `ready`,
  the lesson page keeps re-fetching every 2.5s and shows a live banner, so you
  can return theory first and stream games in later.

Any of `quiz`, `arrange`, `fill`, `catch` may be omitted — the lesson pipeline
skips the stages you don't send.

---

## 4. `POST /topics/{topicId}/complete`

```json
{ "accuracy": 82 }
```

Responds with what was actually stored:

```json
{ "ok": true, "topic_id": "CS101-U1-T1", "accuracy": 82, "recorded": true }
```

`accuracy` is clamped to 0-100 and persisted on the topic row, so progress
survives a cleared browser cache; `recorded` is false if no such topic
exists. `GET /jobs/{jobId}` reads it back as each topic's `completed` /
`accuracy`. The client treats the call as fire-and-forget (failures are
ignored) and also keeps its own copy locally, merging the two so neither
source can clear the other.

---

## 5. Topic images

There is **no** image endpoint. The lookup (Openverse, no API key) runs
server-side as part of generation, and the result is embedded in the
`GET /topics/{topicId}` response above as an optional `image` object:

```json
{ "url": "https://...", "thumbnail_url": "https://...", "title": "...",
  "creator": "...", "license": "cc0", "source_url": "https://..." }
```

When nothing is found the `image` key is **absent entirely** - not `null`,
not `{}`, not `{"available": false}`. The client's only test is whether the
key exists, so there is no loading state and no broken-image placeholder.

---

## 6. `GET /topics/{topicId}/explainability`

The Phase 4/5 trust report for one topic: provider, retrieval trace,
groundedness/faithfulness/hallucination risk, trust score and band,
per-sentence evidence verdicts, source attribution and Shapley values.
Generates the topic first if it has not been generated yet. Returns
`{ "available": false }` rather than an error when there is nothing to
report. Full shape documented in DOCUMENTATION.md section 8.

---

## 7. Reference sources

`GET /subjects/{subjectId}/sources` lists a subject's extra material;
`POST /subjects/{subjectId}/sources` (multipart `file`) adds one, max 2 per
subject. Uploaded sources are chunked into that subject's retrieval index
and used to ground future lesson generation.

---

## CORS

Allow the exact origin the frontend is served from, `GET`/`POST`, and the
`Content-Type` header. The backend's default `CORS_ORIGINS` already covers
`127.0.0.1`/`localhost` on ports 5500 (the documented `python -m
http.server` port), 5173, 3000 and 8080. A browser treats `localhost` and
`127.0.0.1` as different origins, so whichever one is in the address bar is
the one that has to be listed.
