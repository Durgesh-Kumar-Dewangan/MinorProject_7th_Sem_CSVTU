/**
 * Frontend smoke test. No dependencies, no browser, no build step:
 *
 *     cd nsya-frontend && node tests/smoke.mjs
 *
 * It runs the REAL modules against a minimal DOM stub (tests/dom-stub.mjs)
 * and a stubbed backend, then walks a learner through a whole topic:
 * theory -> quiz -> arrange -> fill -> catch -> score -> notes -> complete.
 *
 * The point is the class of bug `node --check` cannot see. `seed` used to be
 * passed to all four exercise games from learn.js without ever being
 * declared - valid syntax, so every static check passed, but a ReferenceError
 * the moment a learner left the theory stage, which silently broke every
 * exercise in the app. Anything like that now fails here instead.
 */
import assert from "node:assert/strict";
import { click, findByText, installDom, textOf } from "./dom-stub.mjs";

const { document, root } = installDom();

/* --------------------------- stubbed backend --------------------------- */

const TOPIC_ID = "CS101-U1-T1";

const topicContent = {
  status: "ready",
  prerequisite_topic_id: null,
  prerequisite_title: null,
  sequence_order: 1,
  generated_by: "template",
  blocks: [
    { id: `${TOPIC_ID}-S1`, title: "What this topic covers", body: "Variables name a value so it can be reused.", source: "syllabus" },
    { id: `${TOPIC_ID}-S2`, title: "From your material", body: "A variable binds a name to a value in memory.", source: "Extracted verbatim from: notes.txt" },
  ],
  quiz: [{ q: "A variable is…", options: ["a name bound to a value", "a file", "a database"], answer: 0 }],
  arrange: [{ term: "Variable", keywords: ["name", "bound", "value"], distractors: ["socket"], definition: "A name bound to a value." }],
  fill: [{ text: "A variable binds a ___ to a value.", answers: ["name"], bank: ["name", "port", "row"] }],
  catch: [
    { term: "Assignment", ok: true },
    { term: "Photosynthesis", ok: false },
  ],
  notes: ["Re-read this before the next topic."],
};

const explainability = {
  available: true,
  generated_by: "template",
  retrieval_used: true,
  retrieval: { method: "hybrid", vector_used: true, keyword_used: true, reranked: true, candidates: 8, selected: 2 },
  retrieved_chunks: [{ snippet: "A variable binds a name…", source: "notes.txt", modality: "text", score: 0.81, rank: 1 }],
  groundedness: 0.62,
  faithfulness: 1.0,
  hallucination_risk: 0.0,
  semantic_similarity: 0.58,
  topic_alignment: 0.7,
  trust_score: 0.83,
  trust_band: "high",
  trust_components: { groundedness: 0.82 },
  trust_weights: { groundedness: 0.3 },
  verdict_counts: { supported: 2, weak: 0, unsupported: 0 },
  flagged_sentences: [],
  similarity_method: "embedding",
  validation_available: true,
  validation_note: null,
  attribution: [{ source: "notes.txt", weight: 1.0 }],
  shap: { available: true, method: "shapley-exact", total_groundedness: 0.62, values: [{ chunk_index: 0, source: "notes.txt", value: 0.62, share: 1.0, snippet: "A variable…" }] },
  evidence_trace: [{ block: "From your material", sentence: "A variable binds a name to a value in memory.", verdict: "supported", similarity: 0.9, reasons: [], chunk_index: 0, source: "notes.txt", modality: "text", evidence: "A variable binds…" }],
  context_relevance: [{ chunk_index: 0, source: "notes.txt", modality: "text", snippet: "A variable binds…", relevance: 0.81, vector_score: 0.77, keyword_score: 0.9, keyword_coverage: 0.9, rank: 1, sentences_supported: 2, shap_share: 1.0 }],
  optimization: { regenerated: false, notes: [] },
};

const job = {
  status: "done",
  phase: "done",
  progress: 100,
  error: null,
  subjects: [
    {
      id: "CS101",
      name: "Computer Science",
      units: [
        {
          id: "CS101-U1",
          number: 1,
          name: "Fundamentals",
          topics: [{ id: TOPIC_ID, name: "Variables", blocks: [], completed: false, accuracy: null, status: "ready" }],
        },
      ],
    },
  ],
};

const calls = [];

globalThis.fetch = async (url, init = {}) => {
  const path = String(url).replace("http://127.0.0.1:8000", "");
  calls.push(`${init.method || "GET"} ${path}`);
  const body =
    path.startsWith("/jobs/") ? job
    : path.includes("/explainability") ? explainability
    : path.startsWith(`/topics/${TOPIC_ID}/complete`) ? { ok: true, topic_id: TOPIC_ID, accuracy: 100, recorded: true }
    : path.startsWith(`/topics/${TOPIC_ID}`) ? topicContent
    : {};
  return { ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body) };
};

/* ------------------------------- helpers ------------------------------- */

let passed = 0;
function check(label, fn) {
  try {
    fn();
    console.log(`  ok   ${label}`);
    passed += 1;
  } catch (err) {
    console.error(`  FAIL ${label}`);
    console.error(`       ${err.message}`);
    process.exitCode = 1;
    throw err;
  }
}

/** Let queued promise callbacks (load(), then draw()) run. */
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

/** The stage pills say which stage is active; read the active one. */
function activeStage() {
  const pill = root.querySelectorAll(".stage-pill").find((p) => p.classList.contains("is-active"));
  return pill ? pill.textContent.trim() : null;
}

function stageNames() {
  return root.querySelectorAll(".stage-pill").map((p) => p.textContent.trim());
}

/* -------------------------------- run ---------------------------------- */

console.log("\nFrontend smoke test (real modules, stub DOM)\n");

// 1. every module must import cleanly.
const modules = [
  "../js/utils.js", "../js/icons.js", "../js/router.js", "../js/store.js", "../js/api.js",
  "../js/shell.js", "../js/job-sync.js", "../js/xai-metrics.js", "../js/xai-panel.js",
  "../js/sources-panel.js", "../js/games/game-shell.js", "../js/games/theory-reader.js",
  "../js/games/quiz.js", "../js/games/arrange.js", "../js/games/fill.js", "../js/games/catch.js",
  "../js/screens/ingest.js", "../js/screens/uploading.js", "../js/screens/extracting.js",
  "../js/screens/graph.js", "../js/screens/arc.js", "../js/screens/pipeline.js",
  "../js/screens/profile.js", "../js/screens/learn.js",
];
for (const m of modules) await import(m);
check(`all ${modules.length} modules import without error`, () => {});

const store = await import("../js/store.js");
const { renderLearn } = await import("../js/screens/learn.js");

store.setJobId("job-1");
store.setSubjects(job.subjects);
store.setJobDone(true);

const cleanup = renderLearn(root, { subjectId: "CS101", unitId: "CS101-U1", topicId: TOPIC_ID });
await settle();
await settle();

check("lesson loads and opens on the theory stage", () => {
  assert.equal(activeStage(), "theory");
  assert.ok(textOf(root).includes("Variables name a value"), "theory body is missing");
});

check("every exercise stage is offered for this content", () => {
  assert.deepEqual(stageNames(), ["theory", "quiz", "arrange", "fill", "catch", "score", "notes"]);
});

check("the explainability trust score reaches the lesson", () => {
  assert.ok(calls.some((c) => c.includes("/explainability")), "explainability was never requested");
  assert.ok(textOf(root).includes("Trust 83%"), `trust chip missing from: ${textOf(root).slice(0, 200)}`);
});

// 2. theory -> quiz. THIS is the step that used to throw ReferenceError:
//    seed is read when the quiz's options object is built.
check("Continue advances from theory into the quiz (regression: undeclared `seed`)", () => {
  click(findByText(root, "Continue"));
  assert.equal(activeStage(), "quiz");
  assert.ok(root.querySelectorAll(".quiz-opt").length >= 3, "quiz options did not render");
});

check("answering the quiz enables submit and advances to arrange", () => {
  const correct = root.querySelectorAll(".quiz-opt").find((o) => o.textContent.includes("a name bound to a value"));
  click(correct);
  const submit = findByText(root, "Submit answers");
  assert.equal(submit.disabled, false, "submit stayed disabled after answering every question");
  click(submit);
  assert.equal(activeStage(), "arrange");
});

check("arrange renders chips, accepts the definition, and advances to fill", () => {
  assert.ok(root.querySelectorAll(".chip").length >= 3, "no keyword chips rendered");
  for (const word of ["name", "bound", "value"]) {
    click(root.querySelectorAll(".chip").find((c) => c.textContent.trim() === word));
  }
  click(findByText(root, "Check definition"));
  assert.ok(textOf(root).includes("Correct arrangement"), "a correct arrangement was not accepted");
  click(findByText(root, "Finish"));
  assert.equal(activeStage(), "fill");
});

check("fill accepts the blank and advances to catch", () => {
  click(root.querySelectorAll(".chip").find((c) => c.textContent.trim() === "name"));
  click(findByText(root, "Check answer"));
  assert.ok(textOf(root).includes("1/1 blanks correct"), `unexpected fill result: ${textOf(root).slice(0, 160)}`);
  click(findByText(root, "Finish"));
  assert.equal(activeStage(), "catch");
});

check("catch scores the picks and advances to score", () => {
  click(root.querySelectorAll(".chip").find((c) => c.textContent.trim() === "Assignment"));
  click(findByText(root, "Submit picks"));
  assert.ok(textOf(root).includes("2/2 terms judged correctly"), `unexpected catch result: ${textOf(root).slice(0, 160)}`);
  click(findByText(root, "Continue"));
  assert.equal(activeStage(), "score");
});

check("the score screen totals every stage at 100%", () => {
  const pct = root.querySelector(".score-ring__pct");
  assert.equal(pct.textContent.trim(), "100%", `expected 100%, got ${pct.textContent}`);
});

check("notes stage lists the subtopics and the study note", () => {
  click(findByText(root, "Read the topic notes"));
  assert.equal(activeStage(), "notes");
  const text = textOf(root);
  assert.ok(text.includes("1. What this topic covers"), "subtopic headings missing from notes");
  assert.ok(text.includes("Re-read this before the next topic."), "study note missing");
});

check("marking complete records progress against the backend", () => {
  click(findByText(root, "Mark topic complete"));
  assert.ok(calls.some((c) => c === `POST /topics/${TOPIC_ID}/complete`), `completion was never posted; calls: ${calls.join(", ")}`);
  const topic = store.getState().subjects[0].units[0].topics[0];
  assert.equal(topic.completed, true, "topic not marked complete in the store");
  assert.equal(topic.accuracy, 100, `expected accuracy 100, got ${topic.accuracy}`);
});

check("a finished job is still re-fetched once, so stored progress can load", () => {
  assert.ok(calls.some((c) => c.startsWith("GET /jobs/")), "a completed job was never re-read");
});

cleanup?.();

console.log(`\n${passed} checks passed\n`);
