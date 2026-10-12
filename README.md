<img width="1920" height="1080" alt="Screenshot (239)" src="https://github.com/user-attachments/assets/3dd39c7b-63fb-45ae-8aa5-8bd18a12051a" /># SYA.ai: An Explainable and Responsible AI Platform  Personalised Learning'(fixed & verified locally)

This is your `NSYA-html` repo (FastAPI backend + vanilla-JS frontend) with the
connection bugs fixed and the full upload → parse → learn flow verified
end-to-end. Two servers, no build step.

# Screenshot of the Project

## 🖥️ UI Showcase

<p align="center"> <img width="1920" height="1080" alt="Screenshot (239)" src="https://github.com/user-attachments/assets/686c1095-fd0a-4cfc-9a2f-a705c8b1b5b9" />

  <img src="screenshots/image-01.png" width="32%" alt="UI Screenshot 1">
  <img src="screenshots/image-02.png" width="32%" alt="UI Screenshot 2">
  <img src="screenshots/image-03.png" width="32%" alt="UI Screenshot 3">
  <img src="screenshots/image-04.png" width="32%" alt="UI Screenshot 4">
  <img src="screenshots/image-05.png" width="32%" alt="UI Screenshot 5">
  <img src="screenshots/image-06.png" width="32%" alt="UI Screenshot 6">
  <img src="screenshots/image-07.png" width="32%" alt="UI Screenshot 7">
  <img src="screenshots/image-08.png" width="32%" alt="UI Screenshot 8">
  <img src="screenshots/image-09.png" width="32%" alt="UI Screenshot 9">
  <img src="screenshots/image-10.png" width="32%" alt="UI Screenshot 10">
  <img src="screenshots/image-11.png" width="32%" alt="UI Screenshot 11">
  <img src="screenshots/image-12.png" width="32%" alt="UI Screenshot 12">
</p>


## Subtopics are now a real, first-class part of the data model

Previously, a topic's "explanation" was a single block (or a few, in later
iterations) stored only as JSON inside the topic's cached content — not a
real, independently addressable entity. This round rebuilds that properly:

- **New `Subtopic` database table**, with a genuine foreign-key
  relationship to its parent `Topic` (`topic_id` FK), its own globally
  unique `subtopic_id` (e.g. `CS101-U1-T1-S3`), an `order_index`, and its
  own title/body/source. This is a real Topic → Subtopic relationship in
  the *data*, not just something implied by JSON structure.
- **The LLM prompt now asks for full subtopic coverage**, not one summary
  block: it's instructed to break the topic into however many genuine
  subtopics it actually has (not padded, not artificially split) and
  explain each one fully — what it is, why it matters, how it fits into
  the topic as a whole.
- **Two new endpoints**: `GET /topics/{id}/subtopics` (lightweight
  id/title/order list — a topic as a parent node with its subtopics as
  small children) and `GET /subtopics/{id}` (one subtopic's full lesson,
  with its parent topic/unit/subject context attached).
- **The Units/Topics page (`pipeline.js`) now renders each topic as a
  parent node with small child dots underneath** representing its actual
  subtopics, each labeled with the subtopic's real title on hover. This
  reads from data already cached client-side for topics that have been
  visited — deliberately **not** an eager fetch for every topic on page
  load, since that would silently force-generate (and burn a real LLM
  call for) every topic in the unit just to render a preview.
- **Regeneration is genuinely wired now.** The frontend's "New round"
  button always sent a `seed` value, but the backend never actually used
  it — confirmed this was dead code from an earlier round and never
  fixed until now. Replaced the vestigial seed mechanism with an explicit
  `regenerate=true` flag, sent only by that button, which forces fresh
  generation — deleting the topic's old subtopic rows and creating new
  ones — bypassing the cache. A normal page load still hits the cache as
  before; only an explicit regenerate click produces new content.

**A real bug found and fixed while building this:** naively wiring
"seed present → force fresh" would have broken caching entirely, since the
frontend sends a seed value on *every* load, including the very first
visit to a topic, not just on regenerate clicks. Caught this before
shipping it by tracing the actual call sites in `learn.js`, not by
assuming the parameter meant what its name suggested.

**Images are resolved synchronously during generation now, not via a
separate lazy-loaded endpoint.** By the time a topic's content is
returned, the backend already knows for certain whether a real, valid
image was found — the `image` key is present in the response only when
one was, and is omitted entirely (not `null`, not an empty placeholder)
otherwise. This removes the loading-spinner / "no image found" states
that existed before: there's nothing to load, so there's nothing to show
while waiting.

**Verified with real tests, not just written:**
- Generated a topic's content and confirmed real `Subtopic` rows appear
  in the database with correct FK linkage, unique IDs, and full body text
- Confirmed three different topics (from different subjects/units) each
  get genuinely distinct subtopic content correctly referencing their own
  subject/unit/topic names, not shared or duplicated text
- Confirmed `regenerate=true` deletes and recreates subtopic rows with no
  duplicates (4 before, 4 after — not 8)
- Re-ran the concurrency lock test against the new subtopic-row logic: 5
  simultaneous requests for one topic still produced exactly 1 real
  generation call and exactly 4 subtopic rows, not a multiple
- Confirmed zero missing or duplicate topics across a full multi-subject
  upload (12 topics across 4 units, all unique, all correctly parented)
- Re-ran the subject-ID collision fix from the previous round against
  this new schema to confirm it still holds
- All 23 frontend JavaScript files pass syntax checking

## What was broken and what I fixed

1. **`/health` was unreachable (404).**
   In `backend/app/main.py`, the syllabus router — which exposes a catch-all
   `GET /{syllabus_id}` route — was registered *before* `/health`. FastAPI/
   Starlette matches routes in registration order, so `GET /health` was being
   matched by `/{syllabus_id}` (treating `"health"` as a syllabus id) and
   returning `404 Syllabus not found` instead of ever reaching the real
   handler. Fixed by moving the `/health` route above `include_router(...)`.

2. **Duplicate, unreachable route handlers.**
   `backend/app/api/routers/syllabus.py` defined `get_job`, `get_topic_content`,
   and the "complete topic" endpoint **twice each** at the same path. Only the
   first definition of each ever ran; the second copies (some with more
   detailed logic) were 100% dead code. Consolidated each into one clean
   handler, keeping the best behavior from each pair.
   Also cleaned up a duplicated `IngestRequest`/`SearchRequest` class
   declaration (with stray blank lines) in `knowledge.py`.

3. **Topics were being silently dropped by the parser.**
   `backend/app/services/parser.py` extracted bulleted syllabus topics with a
   regex requiring the topic text to be **at least 8 characters**. Short but
   completely valid topics like `"Arrays"` (6 chars) or `"SQL"` were silently
   discarded. Lowered that floor to 3 characters for bulleted/numbered list
   items specifically (a bullet already signals "this is a topic" — unlike
   the separate heading-guessing fallback, which still needs a higher bar to
   avoid false positives).

4. **Requirements were far heavier than the app actually needs to run.**
   The original `requirements.txt` pulled in `torch`, `transformers`,
   `paddlepaddle`, `paddleocr`, `camelot-py[cv]`, `psycopg2-binary`, and
   `supabase` — several GB of ML dependencies. All of these are used only for
   optional features (scanned-image OCR, Postgres/Supabase instead of the
   built-in SQLite, and the vector-search endpoints), and the code already
   imports them *lazily* with graceful fallbacks if they're missing. I split
   `requirements.txt` into a lean core set (installs in ~2 minutes) plus a
   commented list of optional extras — see the bottom of that file.

5. **Real multi-subject splitting.**
   Previously `backend/app/services/parser.py` always produced exactly one
   subject per uploaded file, no matter what was in the document — a
   syllabus covering "Computer Science" *and* "Physics" got merged into a
   single subject. Added `_split_into_subjects()`, which detects explicit
   subject-level headings (`Subject: ...`, `Course 2: ...`, `SUBJECT - ...`).
   When 2+ such headings are found, each becomes its own subject with its
   own units/topics parsed independently. When 0 or 1 heading is found
   (the common case), the document is still treated as a single subject
   exactly as before — this is fully backward compatible with every syllabus
   format the parser already supported.
   - Subject IDs are de-duplicated (`P101`, `P101-2`, ...) if two subjects
     would otherwise derive the same id.
   - Fixed a related bug this change surfaced: subject descriptions were
     bleeding into the first unit's text (e.g. "Introduction to programming
     ... Unit 1: Fundamentals\n- Variables..."). Descriptions are now cut
     off at the first unit heading.
   - The frontend needed **no changes** for this — `graph.js`, `arc.js`,
     `learn.js`, `pipeline.js`, and `profile.js` already iterate over
     `subjects` as an array (`subjects.forEach(...)`, `subjects.length`)
     rather than assuming `subjects[0]`, so multi-subject syllabi render
     correctly out of the box.

6. **The knowledge graph existed but was never actually used.**
   `backend/app/services/knowledge_graph.py` builds a NetworkX graph over
   subjects/units/topics with `part_of` and `prerequisite_of` edges, and can
   compute a topological-sort learning roadmap per subject — but it was only
   reachable through a separate, unused API endpoint
   (`/api/v1/knowledge/{id}/graph`). The main upload → parse pipeline never
   called it, and the frontend's own progress UI
   (`nsya-frontend/js/screens/extracting.js`) already expected a
   `extract → distribute → generate → done` sequence that the backend never
   actually sent (`"distribute"` was never reported).

   Rewrote `process_syllabus()` in `backend/app/api/routers/syllabus.py`
   into four explicit stages that match the frontend exactly:
   - **extract** — pull raw text from the uploaded file
   - **distribute** — parse into subject/unit/topic rows, *then* build the
     knowledge graph over them and use it to compute, per topic, its
     position in the subject's learning roadmap (`sequence_order`) and its
     prerequisite topic (`prerequisite_topic_id`) — this is the step that
     actually finds the relationships between topics/units/subjects, not
     just their flat list membership
   - **generate** — mark topics ready (hook point for real AI generation,
     see "Next step" below)
   - **done**

   Added `Syllabus.phase`, `Syllabus.knowledge_graph`, `Topic.sequence_order`,
   and `Topic.prerequisite_topic_id` columns to persist this. Lesson content
   generation (`_topic_content()`) now actually reads the graph-derived
   prerequisite and sequence position and weaves them into the generated
   lesson text and notes (e.g. *"This builds directly on Variables..."*,
   *"This is step 3 in the recommended learning path..."*) — so lesson
   generation is now genuinely informed by the graph relationships, not
   generated per-topic in isolation. The `/api/v1/knowledge/.../graph` and
   `/roadmap` endpoints now reuse the graph stored during this stage instead
   of rebuilding it from scratch on every request.

   **Bug found and fixed along the way:** the graph only chained topics
   sequentially *within* a unit, not across unit boundaries — so topological
   sort had no constraint forcing "finish Unit 1 before Unit 2," and a
   later unit's topic could sort ahead of an earlier unit's topic. Verified
   concretely: before the fix, `Arrays` (Unit 2, first topic) got
   `sequence_order: 2`, jumping ahead of `Functions`/`Conditionals` from
   Unit 1, with no prerequisite recorded. Fixed by chaining all of a
   subject's topics into one continuous sequence across unit boundaries.
   Re-verified directly against the database after the fix — for both the
   single-subject sample and the two-subject sample, `sequence_order` now
   increases strictly (1, 2, 3, 4, 5, 6) with zero interleaving, and
   `Arrays` correctly shows `Conditionals` (the last topic of Unit 1) as
   its prerequisite.

## Automated test suite

Previous rounds of work in this project relied entirely on manual, ad hoc
verification — running scripts by hand each session to re-confirm things
still worked. That's now backed by a real `pytest` suite
(`backend/tests/`) covering the checks that mattered most across this
project's development:

- Full pipeline correctness (single- and multi-subject syllabi, correct
  Unit/Topic distribution with no missing or duplicate topics)
- Knowledge graph sequencing and prerequisites, including the cross-unit
  ordering regression
- Subtopic generation as real database rows, content caching, forced
  regeneration without duplication, and the "no image key unless a real
  image was found" rule
- The concurrency lock (five simultaneous requests for one topic produce
  exactly one real generation call)
- Knowledge graph and roadmap API endpoints
- Both previously-fixed crash bugs: the subject-ID collision between
  separate uploads, and the broken exception handler that used to leave a
  failed upload stuck with no error recorded

Run it yourself:
```bash
cd backend
source .venv/bin/activate   # after running install.sh / install.cmd once
python -m pytest tests
```
**All 65 tests pass** — confirmed by actually running the suite, not just
writing it.

Bugs found and fixed in the suite itself, each a real one:

- The first version of the fixture deleted the SQLite file directly,
  producing spurious "attempt to write a readonly database" errors on
  every test, because SQLAlchemy's pool still held handles against the
  deleted file. Fixed by disposing the pool first.
- Deleting that file still failed on Windows (`PermissionError`,
  WinError 32) whenever a test failed partway through and leaked its
  session, which turned one genuine failure into a cascade of unrelated
  errors in every test after it. Now: dispose, collect, retry, and fall
  back to dropping the tables if the file still will not budge.
- Four tests built a PDF at runtime with `reportlab`, and the HTTP tests
  need `httpx`, but neither was in `requirements.txt` — so on a stock
  install they errored at fixture setup. Both are real entries now.
- The "no image unless one was really found" test depended on the
  machine having *no* internet: it passed offline and failed on any
  machine with a working connection. The lookup is stubbed now, and a
  second test covers the opposite case (an image that IS found must
  reach the client intact).
- Ingestion is keyed by `subject_id`, and the fixtures use real-looking
  ids like `CS101`, so the suite was writing fixture chunks into the
  same FAISS index a developer's running app retrieves from — 36 of them
  were sitting in the live index when this was found. The index
  directory is configurable now (`FAISS_INDEX_DIR`) and the tests point
  it at their own.

### Frontend smoke test

```bash
cd nsya-frontend
node tests/smoke.mjs
```
13 checks, no dependencies and no browser: the real modules run against a
small DOM stub, walking a learner through theory → quiz → arrange → fill
→ catch → score → notes → mark complete.

This exists because of the worst bug in this round: `seed` was passed to
all four exercise games from `learn.js` and never declared anywhere. It
is valid syntax, so every static check passed — but it threw a
`ReferenceError` the moment a learner pressed Continue past the theory
stage, which meant **every exercise in the app was broken**. Nothing
short of running the code could have caught it, so now something does.

## Verified working (locally, in a sandbox — see below for why not a public URL)

- `GET /health` → `200 {"status":"ok","phase":1}`
- `POST /syllabus/upload` (multipart file) → `{"jobId": "..."}`
- `GET /jobs/{jobId}` → polls through `uploaded → processing → parsed`,
  returning the subject/unit/topic tree the frontend renders
- `GET /topics/{topicId}` → generated lesson content (blocks, quiz, arrange,
  fill, catch, notes)
- `POST /topics/{topicId}/complete` → records completion
- Full CORS round trip confirmed from a separate origin
  (`http://127.0.0.1:5500` frontend → `http://127.0.0.1:8000` backend)
- Confirmed the "Arrays" parser bug is fixed — it now appears as its own
  topic instead of being dropped

## How to run it

Installing and running are two separate steps now — one file to install
everything (no server auto-starts), then you run the backend and frontend
yourself from a terminal, e.g. the one built into VS Code
(`` Terminal → New Terminal `` or `` Ctrl+` ``).

### Step 1 — install everything (one time)

**Windows:** double-click **`install.cmd`** in this folder. One command
installs everything:

- the Python virtual environment (`backend/.venv`)
- the CPU-only build of PyTorch (installed *first*, so
  `sentence-transformers` can't drag in a multi-gigabyte CUDA build on a
  machine with no GPU)
- everything in `backend/requirements.txt` — FastAPI, SQLAlchemy, spaCy,
  FAISS, plus the test dependencies (`pytest`, `httpx`, `reportlab`)
- the spaCy English model (`en_core_web_sm`)
- the MiniLM embedding model (~80MB), pre-cached so your first upload
  isn't what waits on a download
- `backend/.env` (copied from `.env.example`, only if you don't have one)
  and `backend/uploads/`

It finishes by **verifying** each piece and printing a status table —
`[OK]` or `[DEGRADED]` per feature — so a failure buried in the install
log can't go unnoticed. The two model downloads are optional: without
them the app still runs (parser uses a fallback pipeline, retrieval runs
keyword-only BM25) and the table says exactly that. It does **not** start
any server — it finishes, tells you it's done, and stops.

If double-clicking does nothing visible, open PowerShell, `cd` into this
folder, and run `.\install.ps1` directly.

**Mac/Linux:**
```bash
bash install.sh
```
Same thing — installs everything, starts nothing.

**Common gotcha (Windows):** if PowerShell says `cd : Cannot find path`,
you're not actually in the folder you think you are — run this to find it:
```powershell
Get-ChildItem -Path C:\Users\<you>\Downloads -Filter "NSYA*" -Recurse -Directory | Select-Object FullName
```

### Step 2 — run it (every time)

**The one-command way:** double-click **`run.cmd`** (Windows) or run
`bash run.sh` (Mac/Linux). It starts the backend on `:8000`, the frontend
on `:5500`, and opens your browser. On Windows each server gets its own
window — close them to stop. On Mac/Linux both run in the one terminal and
`Ctrl+C` stops both.

**Or manually, in two terminals** — nothing launches automatically:

**Terminal 1 — backend** (from the project root):
```powershell
cd backend
.venv\Scripts\Activate.ps1        # Windows
# source .venv/bin/activate       # Mac/Linux — use this line instead
uvicorn app.main:app --host 127.0.0.1 --port 8000
```
Leave this running. You should see `Uvicorn running on http://127.0.0.1:8000`.
Interactive API docs at `http://127.0.0.1:8000/docs`.

**Terminal 2 — frontend** (open a second terminal, same project):
```bash
cd nsya-frontend
python -m http.server 5500
```

Then open **`http://127.0.0.1:5500`** in your browser — that's the actual
app UI (not port 8000, which is just the API).

The frontend is already pointed at the backend via
`nsya-frontend/index.html`:
```html
<script>
  window.NSYA_API_URL = "http://127.0.0.1:8000";
</script>
```
Port 5500 is already in the backend's default `CORS_ORIGINS`, so this
works with no configuration. If you move either side to a different
host/port, change this value **and** `CORS_ORIGINS` in `backend/.env`
together — and note a browser treats `localhost` and `127.0.0.1` as
different origins, so list whichever spelling is actually in your address
bar.

Try it with the included `sample-syllabus.txt`: open the app, upload that
file on the ingest screen, and watch it walk through extracting → the
subject/unit/topic graph → into the interactive lesson screens.

## Why this isn't hosted at a public URL

I ran and tested everything in an ephemeral sandbox that has no route to the
public internet for hosting a live server — so "make it live" here means
"fully working when you run it," which I've verified end-to-end above, rather
than a hosted link. If you want an actual public URL, the cleanest next step
is deploying `backend/` to something like Render/Railway/Fly.io (it's a plain
FastAPI app with SQLite by default — trivial to point at Postgres via
`DATABASE_URL` if you want it persistent) and `nsya-frontend/` to Vercel/
Netlify/GitHub Pages, then updating `window.NSYA_API_URL` and `CORS_ORIGINS`
to match the deployed hosts. Happy to help with that deploy config if you
want to go that route.

7. **Removed the "simulation"/emulation placeholder; added a real web-image
   area per topic.**
   Every topic page had a decorative "Emulation running…" pulsing dot with a
   Play button (`theory-block__emulation` in `theory-reader.js`), tied to a
   fixed one-line `emulation` string like *"Visualize X as a connected
   concept within Y."* — a purely decorative placeholder, not a real
   simulation of anything. Removed it entirely (backend no longer generates
   the `emulation` field; frontend no longer renders that UI).

   In its place, added a real image area at the top of every topic page:
   - **Superseded since:** there is no `GET /topics/{topicId}/image`
     endpoint any more. The lookup moved into generation itself, so the
     result is embedded in the `GET /topics/{topicId}` response as an
     optional `image` object — present only when a real image was found,
     absent entirely otherwise. That removed the client's loading and
     empty states: by the time a lesson renders, whether it has an image is
     already settled. The rest of this entry still describes the lookup
     accurately; only its delivery changed.
   - A lookup in `backend/app/services/image_lookup.py` that finds one real,
     freely-licensed image for the topic via the **Openverse API**
     (`api.openverse.org`) — a free, keyless search over openly-licensed
     images (Creative Commons etc.) sourced from Wikimedia Commons, Flickr,
     museums, and more. Uses only the Python standard library
     (`urllib`), so it adds no new dependency.
   - Fails soft everywhere: any network error, timeout, or empty result
     just returns `{"available": false}` rather than a 404/500 — the lesson
     page never breaks because an image couldn't be found. Directly verified
     this in a network-restricted sandbox where the lookup genuinely can't
     reach the internet: it returned `None`/`{"available": false}` cleanly,
     no exception, no crash.
   - Frontend (`theory-reader.js`) shows a loading spinner, then either the
     fetched image (with a link to its source and attribution/license line)
     or a plain "No image found for this topic" empty state — never a
     broken image icon or console error.

   **Note on network access:** I could only verify the graceful-fallback
   path in this sandbox, since its outbound network is restricted and can't
   reach `api.openverse.org`. On your machine (normal internet access) it
   should return real images — try it and let me know if anything looks
   off. If Openverse ever comes back empty for topics that are too obscure
   or oddly worded, the easiest fix is loosening the search query in
   `image_lookup.py`'s `find_topic_image()` call inside `get_topic_image()`.

## Confirmed: subject → unit → topic navigation

Walked through this end-to-end in the code to confirm it's wired exactly as
expected:
```
#/graph                              subjects (click one)
  → #/arc/:subjectId                 that subject's units (click one)
    → #/pipeline/:subjectId/:unitId  that unit's topics (click one)
      → #/learn/:subjectId/:unitId/:topicId   lesson page
```
`graph.js`, `arc.js`, and `pipeline.js` all navigate correctly into the next
level down. If you're seeing something different in practice (e.g. clicking
a subject doesn't show its units, or topics appear in the wrong subject),
that's a specific bug worth reporting with what you clicked and what
happened — the routing code itself is correct, so a real bug there would be
narrow and worth tracking down precisely rather than guessing at.

## Hybrid LLM lesson generation (Ollama + Mistral + Groq + Gemini)

Lesson content generation now tries a chain of LLM providers before falling
back to the deterministic template generator that was there before. This is
genuinely **hybrid**: one provider runs entirely on your own machine, the
other three are cloud APIs with free tiers.

| Provider | Where it runs | Cost | Setup |
|---|---|---|---|
| **Ollama** | Local (your machine) | Free, no limits, works offline | Install [ollama.com](https://ollama.com), run `ollama serve`, then `ollama pull llama3.2` |
| **Mistral** | Cloud | Free tier | API key from [console.mistral.ai](https://console.mistral.ai) |
| **Groq** | Cloud (very fast inference) | Free tier | API key from [console.groq.com](https://console.groq.com) |
| **Gemini** | Cloud | Free tier | API key from [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |

Keys go in `backend/.env`, which is only read at startup — **restart the
backend** after editing it. Then open a lesson's trust chip and check
*"Generated by"*: it should name the provider, not `template`.

If it still says `template`, the report's **"Which model wrote this"**
section now tells you why, one line per provider tried:

```
[groq   ] HTTP 400: The model `llama-2-70b-chat` has been decommissioned
[mistral] no API key set (MISTRAL_API_KEY)
```

That matters because a rejected key, a retired model name and "nothing
configured" used to look identical — all three just produced a template
lesson labelled *"no LLM configured"*. Hosted models do get retired, so if
you see a 400 there, check the model name against your provider's console.

The whole request/response path for all four providers is covered by
`backend/tests/test_llm_providers.py` (endpoint, auth header, body, parsing,
fence-stripping, fallback order, and each failure mode) with `urlopen`
faked — so the only part your own key is needed for is the network hop
itself.

## Every topic gets its own real, substantive explanation

Without an LLM key configured, the template fallback used to produce one
thin sentence per topic ("X is a focused subtopic in Y..."), which wasn't
a real explanation, just a placeholder. Rewrote it into three genuinely
separate blocks per topic:

1. **What this topic covers** — frames the specific topic within its unit
   and subject, and states plainly that it's a distinct learning target,
   not a repeat of the topics around it
2. **Where it fits** — explains its actual prerequisite relationship (from
   the knowledge graph) and its position in the subject's learning path,
   e.g. *"This topic comes right after Conditionals... Conditionals lays
   groundwork that Arrays builds on"*, or, for an entry-point topic,
   *"nothing earlier in this unit is marked as a prerequisite for it"*
3. **How to work through it** — honest study guidance: read the original
   syllabus material alongside this if you have it (the template is a
   scaffold, not a replacement for real subject content), then actually
   use the exercises to test recall

**Important honesty note, since this matters for what "explanation" means
here:** the template has no real subject-matter knowledge — it can't
truthfully explain *what a variable is* or *what Newton's First Law says*
without either fabricating facts or having an actual knowledge base. What
it *can* do honestly is explain each topic's real structural context —
its subject, unit, prerequisite, and position — which is genuinely
different, verified different, for every topic. Getting real conceptual
teaching content (the actual substance of "what is a variable") requires
a configured LLM key — that's the difference between the template path and
the hybrid LLM path described above, and it's an important distinction to
keep straight rather than call both "proper explanation" without
qualification.

**Verified directly:** pulled the actual generated content for two
different topics (one an entry point with no prerequisite, one with a
real prerequisite from the knowledge graph) and confirmed each gets a
distinct, three-block explanation correctly reflecting its own subject,
unit, and prerequisite relationships — not the same text with the topic
name swapped in.

## Images are chosen by the LLM, and constrained to diagrams only

Real AI *image generation* (DALL-E-style, pixels created from scratch) isn't
wired in, and I want to be upfront about exactly why rather than quietly
skip it: none of the four providers above offer free image generation —
only free text generation. Adding real image generation would mean either a
paid API (extra cost, breaks the free-by-default design this whole project
follows) or running a local image model, a much heavier, GPU-realistic
install than anything else here. Neither fit.

What *is* now genuinely LLM-driven: the same LLM call that writes a topic's
lesson also decides `image_query` — a short, specific search phrase for
what should visually represent that particular lesson's content, not just
a mechanical restatement of the topic title. That query is what actually
gets searched against the free Openverse image API (see
`backend/app/services/image_lookup.py`).

**Diagram-only, not photographs.** Two changes enforce this:
- The Openverse query is constrained with `categories=illustration` — the
  API's real, documented filter for diagrams/schematics/infographics as
  opposed to photographs. Verified this is the correct, current parameter
  name directly against Openverse's API documentation before using it.
- The prompt asks the LLM specifically for a diagram/schematic/chart-style
  phrase (e.g. `"inertia force diagram"`), not a photo-oriented one (e.g.
  *not* `"Newton's cradle demonstration"`, which would return a photograph).
  The deterministic template's fallback query is built the same way —
  `"{topic} {unit} diagram"`.
- Deliberately **no fallback to an unfiltered search** if no diagram is
  found for a given topic — the topic just shows no image rather than
  falling back to a random photograph, since a photo isn't an acceptable
  substitute here.

**Fallback chain, in order (all diagram-constrained):** the LLM's own
`image_query` → topic title + unit name + "diagram" (if the LLM's query
finds nothing, or the topic was template-generated and has no LLM query to
use) → bare topic title + "diagram" (last resort). `GET /topics/{id}/image`
still returns `query_used`, so you can see exactly which query found the
result.

**Verified directly:** confirmed the `categories=illustration` parameter is
correctly included in the constructed Openverse request URL; confirmed a
template-generated topic's `image_query` ends in "diagram"; confirmed —
using a mocked provider response — that an LLM-provided diagram-style query
is correctly stored and used over the generic fallback; confirmed the image
endpoint still runs cleanly end-to-end through this whole chain with zero
network access, same graceful-fallback behavior as before.

**How it works** (`backend/app/services/llm_client.py`):
- Providers are tried in the order set by `LLM_PROVIDER_ORDER` in `.env`
  (default: `ollama,mistral,groq,gemini`) — first one that returns a valid
  response wins.
- Each provider is skipped automatically if it's not configured (no API
  key set) or unreachable (network error, timeout, bad response) — no
  crashes, just moves to the next one in the chain.
- The prompt asks for the exact same JSON shape the frontend already
  expects (`blocks`, `quiz`, `arrange`, `fill`, `catch`, `notes`), grounded
  in the topic's title, its unit/subject context, its knowledge-graph
  prerequisite, and an excerpt of the original uploaded syllabus text.
- If every provider fails (or none are configured — the default, out-of-
  the-box state), it falls back to the same template generator that was
  there before. **Zero configuration = the app still works exactly as it
  did before this feature existed.** Adding any one API key upgrades that
  topic's lessons to real generated content.
- The response includes a `generated_by` field (`"ollama"`, `"mistral"`,
  `"groq"`, `"gemini"`, or `"template"`) so you can see which path actually
  produced a given lesson.
- **Cached, not re-generated every visit.** A real LLM call costs real
  free-tier quota, so the first time a topic's lesson is requested, the
  result (whichever provider produced it) is saved on that `Topic` row
  (`generated_content`, `generated_by` columns) and reused on every later
  visit — verified directly: calling the same topic twice returns identical
  content the second time, with no second generation call made. One
  pre-existing caveat this surfaces: the frontend's quiz/arrange/fill "New
  round" button re-requests the same endpoint expecting a different set of
  questions, but the backend has never actually varied output by the `seed`
  parameter it's sent (that was true before this change too) — with caching
  now in place this is worth fixing together if you want real regeneration
  on "New round," since right now it'll just show the same cached exercise
  again.

**To turn it on:** open `backend/.env`, fill in whichever provider(s) you
want (a Groq or Gemini key takes about a minute to get and is the fastest
way to test this — Ollama needs installing separate software, Mistral needs
a signup + card-less free-tier key), then restart the backend.

**What I verified vs. what needs your machine to confirm:** I tested the
JSON-parsing/validation logic directly (including realistic markdown-fenced
model output) and confirmed the full fallback chain — no providers
configured → returns `None` → template generator kicks in cleanly, with the
multi-subject subject-title lookup bug this surfaced (was always grabbing
the *first* subject regardless of which one a topic actually belonged to)
found and fixed along the way. I could **not** test a real Mistral/Groq/
Gemini/Ollama call end-to-end, since this sandbox's network can't reach
any of those hosts. Add a real key (Groq's free tier is the quickest to set
up) and try uploading a syllabus — let me know what `generated_by` shows
and whether the lesson text reads like real generated content.

**Fallback chain, tested with a realistic failure scenario:** I simulated
the exact situation this is built for — Ollama unreachable (no local
server running), Mistral returning something that isn't valid JSON
(a refusal-style response), Groq returning a correctly-shaped lesson.
Confirmed directly: the chain calls `ollama` → gets nothing → tries
`mistral` → gets invalid JSON, discards it → tries `groq` → gets a valid
lesson → stops there and returns it, correctly tagged
`generated_by: "groq"`, without ever falling through to Gemini or the
template. This is the actual hybrid-fallback behavior working, not just
the single-provider or all-fail cases tested earlier.

**On Kimi specifically:** checked current pricing before considering
adding it — Moonshot AI's Kimi API has no free tier as of now; it requires
a minimum paid top-up before it answers any request. Left out of the
default provider chain for that reason (this app's whole design principle
is free-by-default). Happy to add it as a fifth, clearly-labeled paid
option if you want it later.

**Llama, for the record:** already covered twice over without a dedicated
"Llama" entry — Ollama runs `llama3.2` locally, and Groq's default model
(`llama-3.1-8b-instant`) *is* a Llama model served fast in the cloud.

## RAG (retrieval-augmented generation) — real, not just context-stuffing

Before this, "grounding" the LLM meant blindly truncating the syllabus's raw
extracted text to the first 1500 characters — the same slice for every
topic, regardless of relevance. That's not RAG, just naive context
stuffing. It's now real retrieval:

**How it works** (`backend/app/services/embeddings.py` +
`backend/app/services/llm_client.py`):
- During the **distribute** pipeline stage, the syllabus's raw text is
  chunked (paragraph-aware — splits on blank lines, merges short
  paragraphs up to ~400 chars, only falls back to character-based
  splitting for a single oversized paragraph) and embedded into **one
  FAISS index per subject** using `sentence-transformers/all-MiniLM-L6-v2`
  (swapped in place of the much larger BAAI/bge-m3 that was originally
  stubbed in here — MiniLM is ~80MB and CPU-friendly, appropriate for
  "install this and it runs on a normal laptop").
- When generating a topic's lesson, instead of the naive excerpt, the
  topic's title + unit context is embedded and used to **search that
  subject's FAISS index** for the top-4 most semantically relevant chunks
  of the actual syllabus — genuine retrieval, ranked by cosine similarity,
  not a fixed slice.
- This is the "multi-model" part: one model (MiniLM) handles retrieval,
  a separate model — whichever of Ollama/Mistral/Groq/Gemini answered
  first — handles generation. Two different models doing two different
  jobs in one pipeline.
- Response includes `retrieval_used: true/false` so you can see whether a
  given lesson was actually grounded by real retrieval or fell back to the
  naive excerpt.
- **Fails soft everywhere**, same as the rest of this app: if
  `faiss`/`sentence-transformers` aren't installed, ingestion is skipped
  silently during the pipeline and retrieval returns nothing at generation
  time — falls straight back to the naive excerpt. Nothing about upload,
  parsing, or generation breaks if this layer isn't set up.

**Turning it on:** these are real dependencies now (not just documented as
optional extras) — `faiss-cpu` and `sentence-transformers` are in
`requirements.txt`. One important gotcha I hit and want to flag clearly:
**the default `sentence-transformers` install pulls a CUDA-enabled PyTorch
build**, which tries to download/load NVIDIA GPU libraries even if you have
no GPU — on a typical laptop this is multiple unnecessary gigabytes, and on
Linux without those CUDA libraries present it can flat-out fail to import.
If you hit that, install the CPU-only PyTorch build *first*, then let
`pip install -r requirements.txt` proceed normally:
```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
```
(`run.sh`/`start.cmd` don't do this automatically yet — if your install
hangs or balloons in size, this is almost certainly why. Worth adding to
the setup scripts if this trips you up.)

**What I verified vs. what needs your machine to confirm:** I could not
fully test this in this sandbox — its network can't reach
`download.pytorch.org` for the CPU-only wheel, and its disk didn't have
room for the full CUDA-enabled default build (ran out of space mid-install,
which is exactly the gotcha described above, hit firsthand). What I *did*
verify directly and rigorously:
- `faiss-cpu` installs and imports cleanly (found and fixed a real
  `numpy` 1.x/2.x ABI incompatibility in the process — bumped the pinned
  version from `1.8.0.post1` to `1.9.0.post1`)
- The full ingest → chunk → embed → index → retrieve pipeline, tested with
  a mocked embedding function standing in for the real model (since the
  real model couldn't be loaded here) — confirmed retrieval correctly
  surfaces the topically-relevant chunk for a given query and doesn't mix
  unrelated content, both before and after tightening the chunker to
  respect paragraph boundaries
- `embeddings.py` now imports cleanly even with zero RAG deps installed
  (both `faiss` and `sentence_transformers` were hard top-level imports
  before; moved both inside the functions that actually need them) — this
  was a real robustness gap where a partial install (one dependency present,
  not the other) would have crashed anything touching this module
- The whole upload → extract → distribute → generate pipeline still runs
  correctly end-to-end with `faiss` installed but `sentence-transformers`
  deliberately absent, confirming the fail-soft fallback actually holds

**What's unverified:** a real call through the actual MiniLM model — I
never got a working install of it in this environment. The retrieval
*logic* is tested and correct; whether the *real* embeddings produce
retrieval quality this good in practice is what your machine needs to
confirm. Try the CPU-only-torch install above, upload a syllabus, and check
a topic's `retrieval_used` field.

## Explainable AI panel + optional reference sources

Two small, deliberately unobtrusive additions — neither touches the main
learning flow, both tucked into corner controls.

**1. "How was this lesson made" panel** (small `?` icon, top-right of every
lesson page): click it and it shows, for that specific topic:
- which provider generated it (`ollama`/`mistral`/`groq`/`gemini`/`template`)
- whether real RAG retrieval was used, or it fell back to a plain excerpt
- if retrieval was used, the actual source snippets it pulled from, tagged
  by where they came from (the original syllabus, or an uploaded reference
  doc — see below), plus their similarity score

Backend: `GET /topics/{id}/explainability`. Data comes from what
`llm_client.py` already captures during generation (which chunks got
retrieved, from where, at what score) — this feature just persists and
surfaces that instead of throwing it away after the prompt was built.
Generates the topic first if it hasn't been yet, so this never returns an
empty panel for an unvisited topic.

**2. Optional reference sources per subject** (small "sources" icon,
top-right of the units/arc page): lets you upload 1–2 extra documents per
subject — a textbook chapter, lecture notes, anything — on top of the main
syllabus file. These get chunked and embedded into that subject's FAISS
index alongside the syllabus text (tagged `reference:<filename>` so the
explainability panel can show which one a snippet came from), giving RAG
retrieval better material to draw from. Capped at 2 per subject
server-side; a 3rd upload attempt gets a clear 400 rejecting it.

Backend: `POST` / `GET /subjects/{id}/sources`.

**Verified, not just written:**
- Full HTTP round-trip through the FastAPI test client: uploaded a
  reference doc, listed it back correctly, uploaded a second, confirmed a
  third gets rejected with the cap-reached error message
- `GET /topics/{id}/explainability` tested both directly and through the
  full HTTP stack — correct shape, correct data
- Confirmed the *pre-generated* unit-entry topics (see "Progressive lesson
  pre-generation" above) also get explainability data populated
  automatically — not just topics generated on-demand through the GET
  endpoint, since both paths share the same underlying
  `_ensure_topic_generated()` function
- All 4 touched/new frontend files (`arc.js`, `learn.js`,
  `theory-reader.js`, `api.js`) pass a plain JS syntax check; CSS brace
  count verified balanced (330 open / 330 close) after catching and fixing
  a mistake I made mid-edit where I accidentally deleted a shared rule's
  body while merging two corner-button styles together
- Full upload → extract → distribute → generate pipeline re-run after all
  of this — sequence ordering and prerequisites across both subjects in the
  test file still correct, no regressions

**What's unverified:** I reasoned through the CSS positioning (`.page`
needs `position: relative` for the corner buttons to anchor correctly
instead of floating relative to the whole viewport, confirmed that rule is
present) but never actually rendered this in a browser to see it. If the
corner icons look misplaced or overlap something when you try it, that's
the first thing to check.

## Two more real bugs found during a from-scratch verification pass

Doing a genuine clean-slate re-verification (fresh venv, fresh database)
surfaced two real, previously-undiscovered bugs — not from new features,
from actually re-testing existing code against a scenario I hadn't tried
before: uploading two separate syllabi that happen to share subject/unit/
topic naming.

**Bug 1 — topic_id collisions across separate uploads.**
`derive_subject_id()` (`parser.py`) is a deterministic function of the
subject's title text alone, with no per-upload uniqueness. That's fine for
one upload, but `topic_id` is globally unique across *all* syllabi in the
database (`"CS101-U1-T1"`). Two different uploads that both happen to
produce a subject titled "Computer Science" with a unit called
"Fundamentals" and a topic called "Variables" would derive the *identical*
`topic_id` and collide — crashing the second upload with a database
integrity error. Reproduced this directly by uploading the same sample file
twice in a row and watching it crash exactly as described.

**Bug 2 — the crash handler itself was broken.**
Investigating bug 1 surfaced a second, compounding problem: the pipeline's
exception handler tried to `db.commit()` the `status = "failed"` state
without first calling `db.rollback()`. When the original failure was itself
a database error (like bug 1), the session was left in a broken
"pending rollback" state, so this second commit attempt *also* raised —
meaning the failure was never actually recorded. The syllabus would just
stay stuck on `"processing"` forever, with no error message, no way to
tell what happened.

**Fixes:**
- `_disambiguate_subject_ids()` runs right after parsing: it checks whether
  a subject's derived ID already belongs to a *different* syllabus's
  topics in the database, and if so, rewrites that subject's ID (and every
  topic under it) to a disambiguated version unique to this upload —
  before any rows are created, so the collision never happens in the first
  place.
- The exception handler now calls `db.rollback()` before attempting to
  record the failure, so a genuine error is always correctly saved with
  its message instead of silently getting stuck.

**Verified with real reproduction tests, not just written:**
- Uploaded the same syllabus file twice in the same database — confirmed
  both succeeded, confirmed the second upload's subject was disambiguated
  (`CS101` → `CS101-8ec4`), confirmed zero overlap between the two
  syllabi's `topic_id` sets
- Forced a genuine, unrelated failure (a missing source file) and confirmed
  the syllabus correctly ends up `status="failed"` with a real error
  message, rather than crashing the handler itself
- Re-ran the standard single-upload pipeline test afterward to confirm
  neither fix changed normal, non-colliding behavior

## No duplicate generation — race condition found and fixed

With pre-generation running in the background (unit entries right after
upload, next-topic on completion) alongside on-demand generation from a
live page visit, there's a real timing gap where two different code paths
could both try to generate the *same* topic at almost the same moment —
e.g. the background pre-gen job for a unit's first topic hasn't finished
yet when someone opens that exact topic page. Without a guard, both would
pass the "not yet generated" check and both would fire a real, wasted LLM
call.

Fixed with a per-topic lock (`app/api/routers/syllabus.py`): the first
caller for a given `topic_id` generates normally; any other caller for that
same topic waits, then re-checks the database once it gets the lock — by
then the first caller has usually already saved the result, so the second
caller just uses that instead of generating its own. Verified directly with
a real concurrency test: 5 threads simultaneously requesting the same
ungenerated topic resulted in exactly 1 real generation call, and all 5
still received valid content back.

(Single-process only — this uses an in-memory lock, so it holds for how
this app is meant to run, one `uvicorn` process. If you ever ran multiple
backend processes behind a load balancer, this particular guard wouldn't
coordinate across them and you'd need a real distributed lock instead —
not a concern for local/single-instance use.)

## No more bouncing icons, serial numbering on the subjects page

Found the real cause of the "duplicate icon" look on the subjects page:
`graph.js` had every subject node running its own `infinite` CSS float
animation, restarted from scratch on every store update (which, combined
with the redundant-redraw bug fixed above, meant a full animation restart
every 2 seconds while a job was polling). Removed that animation entirely
— subject nodes are now static, positioned around the orbit with no
continuous motion.

Also switched what number each subject node shows: it used to show that
subject's *unit count* (e.g. "4" for a subject with 4 units, labeled
"units" underneath) — now it shows the subject's **serial position**
(1, 2, 3...) matching how units (`arc.js`) and topics (`pipeline.js`)
already numbered themselves. The unit count is still there, just moved to
the label text underneath (`"4 units"`) instead of being the headline
number.

Checked `arc.js` (units page) and `pipeline.js` (topics page) for the same
bounce/duplicate-number issues while I was at it — both were already
correct: `arc.js` uses a static wheel-scroll-driven scale/opacity (not a
looping animation) and already numbers units sequentially from the
backend's `unit_number`; `pipeline.js` already numbers topics `i + 1`
per unit with no looping animation either. No changes needed there.

## Optional: pre-generate every topic immediately (not just unit entries)

By default, only each unit's *first* topic is pre-generated right after
distribution (see "Progressive lesson pre-generation" below) — a deliberate
cost tradeoff, since generating every topic in a syllabus nobody's finished
reading yet burns free-tier LLM quota for nothing.

If you want the whole pipeline to feel fully real-time — every topic in
every unit already generated and cached the moment extraction/distribution
finishes, so navigating anywhere in the subject is instant with zero
waiting on any topic — set `PREGENERATE_ALL_TOPICS=true` in `backend/.env`.

Verified directly, both ways: with the default settings, a 6-topic test
syllabus came out of the pipeline with exactly the 2 unit-entry topics
pre-generated and the other 4 still lazy. With `PREGENERATE_ALL_TOPICS=true`
set, the same syllabus came out with all 6 topics already generated and
cached, zero left lazy.

**The real tradeoff, stated plainly:** this is one real LLM API call per
topic, made unconditionally, whether or not that topic is ever opened. For
a 4-unit × 5-topic subject, that's 20 guaranteed calls per upload instead
of the ~4 unit-entry calls the default makes — and it happens synchronously
as part of the upload pipeline, so a large syllabus will take noticeably
longer to finish processing with this on. Turn it on if instant, zero-wait
navigation everywhere matters more than API cost/upload speed for your use
case; leave it off (default) otherwise.

## Progressive lesson pre-generation

Two things now happen automatically, on top of the on-demand generation
described above:

1. **First topic of every unit is pre-generated right after upload
   finishes** — not the whole subject, just the entry point of each unit,
   so opening any unit for the first time never makes the learner wait on
   a live LLM call. Verified directly against the database: after
   processing a two-subject syllabus, exactly the 4 unit-entry topics
   (`CS101-U1-T1`, `CS101-U2-T1`, `P101-U1-T1`, `P101-U2-T1`) came back
   with `generated_content` populated; every other topic remained
   ungenerated until visited.
2. **Completing a topic triggers generating the next topic in that
   subject's sequence, in the background** — so by the time the learner
   navigates forward, it's usually already cached instead of generating
   live in front of them. Verified directly: completing `CS101-U1-T1`
   (sequence 1) correctly scheduled and generated `CS101-U1-T2`
   (sequence 2), confirmed ungenerated before and generated+cached after.

Both are controlled by `PREGENERATE_UNIT_ENTRY_TOPICS` and
`PREGENERATE_NEXT_ON_COMPLETE` in `.env` (default `true` for both) if you'd
rather generate purely on-demand to control LLM API usage more tightly —
each pre-generation is a real call against whichever provider answers
first, same cost as an on-demand one, just triggered earlier.

This is **not** "generate the whole subject up front" — topics beyond a
unit's entry point, and topics more than one step ahead of wherever the
learner currently is, are still only generated the first time they're
actually opened. That's a deliberate cost/latency tradeoff: pre-generating
everything would burn free-tier quota on topics that might never be
visited.

## What the loading screen looks like now

Removed the 6-second canvas jump-game (`mario-loader.js`) that used to show
while a lesson's content was being generated — deleted the file, the CSS
for it, and the artificial wait tied to it. `learn.js` now just shows a
plain spinner + "Loading your lesson..." and moves straight to the theory
screen the moment content actually arrives (or an error does), instead of
waiting out a fixed timer regardless of how fast generation actually was.
Verified `learn.js`, `theory-reader.js`, and `api.js` still pass a plain
JS syntax check after this and the rest of this round's edits.

## Optional features not wired up (by design, to keep setup fast)

These are already coded and lazily imported — they just need extra deps if
you want them:
- **OCR for scanned PDFs/images** (`paddlepaddle`, `paddleocr`) — text-layer
  PDFs and `.txt` files already work without this. Run **`install-ocr.sh`**
  (Mac/Linux) or **`install-ocr.cmd`** (Windows) from the project root
  *after* the main install to add it — a separate script since these are
  large packages (paddlepaddle alone is several hundred MB) most people
  won't need. Uploading a scanned document without this now fails with a
  clear message telling you to run that script, instead of a raw
  `ModuleNotFoundError`.
- **Postgres/Supabase** instead of SQLite (`psycopg2-binary`, `supabase`,
  plus setting `DATABASE_URL` in `.env`).

Note that **vector search is not in this list** — `faiss-cpu` and
`sentence-transformers` are ordinary entries in `requirements.txt`, so
`install.cmd` sets them up along with the embedding model, and
`/api/v1/knowledge/ingest` + `/search` work out of the box. (An earlier
version of this list claimed otherwise.) If the model genuinely can't be
loaded, `/search` answers `503` with the reason rather than a bare `500`,
and lesson retrieval degrades to keyword-only BM25 and says so in the
trust report.

Install whichever of those you need from the commented section at the bottom
of `backend/requirements.txt`.
