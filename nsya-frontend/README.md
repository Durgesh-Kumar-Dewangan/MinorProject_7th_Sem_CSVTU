# SYA.ai: An Explainable and Responsible AI Platform  Personalised Learning

This is a straight conversion of the original React/TanStack frontend into
plain HTML, CSS and JavaScript (ES modules, no build step, no framework).
The visual design, layout, spacing, colors, animations and interaction
behaviour are ported 1:1 — nothing was redesigned.

It talks to your existing Python backend using the **exact same contract**
as the original app (see `backend-api.md`, copied from `docs/backend-api.md`
in the source repo — unchanged).

## Run it

No build tools needed. Any static file server works:

```bash
cd nsya-frontend
python3 -m http.server 5500
# open http://127.0.0.1:5500
```

Or just double-click `index.html` — everything is a `<script type="module">`,
which works from `file://` in most browsers, though a local server is more
reliable (some browsers restrict `fetch`/modules on `file://`).

## Connect it to your backend

Open `index.html` and edit the one line near the top:

```html
<script>
  window.NSYA_API_URL = "http://127.0.0.1:8000";
</script>
```

Point it at wherever your FastAPI/Flask/Django server runs. That's the only
change required — every API call in `js/api.js` reads from `window.NSYA_API_URL`.

Make sure your backend's CORS config allows the origin you're serving this
frontend from, and allows `GET`/`POST` + the `Content-Type` header (same
requirement as the original app).

## Endpoints expected

- `POST /syllabus/upload` — multipart `file` → `{ jobId }`
- `GET /jobs/{jobId}` — polled while a job runs; each topic carries its
  stored `completed` / `accuracy`
- `GET /topics/{topicId}?regenerate=<bool>` — lesson content (there is no
  `seed` parameter; exercise shuffling is client-side)
- `POST /topics/{topicId}/complete` — `{ accuracy }`, fire-and-forget on
  the client, persisted on the server
- `GET /topics/{topicId}/subtopics`, `GET /subtopics/{subtopicId}`
- `GET /topics/{topicId}/explainability` — the Phase 4/5 trust report
- `GET`/`POST /subjects/{subjectId}/sources` — reference material, max 2
- `GET /api/v1/knowledge/{syllabusId}/roadmap/{subjectId}` — learning order

Full field-by-field contract: see `backend-api.md`.

## Project structure

```
index.html              entry point — routes hash-navigate through js/main.js
css/styles.css           full design system: oklch color tokens, radii,
                          animations, every screen's layout (ported from
                          src/styles.css + all Tailwind utility usage)
js/
  main.js                registers routes and boots the router
  router.js               tiny hash router (#/…): no server config needed
  api.js                  backend client — 1:1 port of src/lib/api.ts
  store.js                localStorage-backed state — port of src/lib/nsya.ts
  job-sync.js              live-polling helper — port of hooks/useJobSync.ts
  shell.js                 wordmark + side rail + back button (PageShell.tsx)
  icons.js                 inline-SVG icon set (replaces lucide-react)
  utils.js                 el() DOM helper, shuffle(), toast()
  screens/
    ingest.js               "/"                      — upload/drop screen
    uploading.js             "/uploading"              — upload progress
    extracting.js            "/extracting"             — job status polling
    graph.js                 "/graph"                  — subject nodes
    arc.js                   "/arc/:subjectId"         — units arc
    pipeline.js               "/pipeline/:subjectId/:unitId" — topic list
    learn.js                  "/learn/:subjectId/:unitId/:topicId" — lesson canvas
    profile.js                "/profile"                — progress + stats
  games/
    game-shell.js             shared game chrome (icon/title/regenerate/footer)
    theory-reader.js          readable theory blocks + real web image lookup
    quiz.js                   multiple-choice quiz
    arrange.js                tap-to-arrange keyword game
    fill.js                   fill-the-blank game
    catch.js                  catch-the-concept game
tests/
  smoke.mjs                 `node tests/smoke.mjs` — runs the real modules
                             through a whole lesson, no deps, no browser
  dom-stub.mjs              the minimal DOM that makes that possible
```

## Tests

```bash
node tests/smoke.mjs
```
13 checks covering the full lesson flow (theory → quiz → arrange → fill →
catch → score → notes → complete). Worth running after any change to
`screens/learn.js` or `games/*`: these modules only fail at runtime, and
an undeclared variable in them silently breaks every exercise in the app
while passing `node --check` and every linter.

## Notes on the port

- **Routing**: the original used TanStack Router's file-based routes
  (`/arc/$subjectId`, etc.). This build uses a tiny hash router with the
  same path shapes (`#/arc/:subjectId`), so no server rewrite rules are
  needed — you can host this as static files anywhere.
- **State**: `js/store.js` is a plain pub/sub store backed by
  `localStorage`, replacing React's `useSyncExternalStore` store in
  `lib/nsya.ts`. Same merge semantics (backend names win, local progress —
  `completed`/`accuracy` — is preserved across polls).
- **Rendering**: no virtual DOM — each screen module renders into a
  container and re-draws the parts that change (same idea as the original
  screens re-rendering on state change, just without React).
- **Icons**: `js/icons.js` reimplements the small set of lucide-react icons
  actually used (upload cloud, check, alert, spinner, etc.) as inline SVG,
  so there's no icon-font/npm dependency.
- **Fonts**: Inter Tight is loaded from Google Fonts in `styles.css`; swap
  for a self-hosted font file if you need to work offline.
