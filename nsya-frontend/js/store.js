/**
 * Local app state — a plain pub/sub store (vanilla port of lib/nsya.ts's
 * useSyncExternalStore-based store). Persists to localStorage so a refresh
 * doesn't lose progress.
 */

const KEY = "nsya.state.v1";

const initial = {
  fileName: null,
  fileSize: 0,
  jobId: null,
  jobDone: false,
  subjects: [],
  topicStages: {}, // topicId -> last stage the learner was on (theory/quiz/arrange/fill/catch/score/notes)
};

let state = { ...initial };
let pendingFile = null;
const listeners = new Set();

function emit() {
  listeners.forEach((l) => l(state));
}

function persist() {
  try {
    localStorage.setItem(KEY, JSON.stringify(state));
  } catch {
    /* ignore */
  }
}

function hydrate() {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) state = { ...initial, ...JSON.parse(raw) };
  } catch {
    /* ignore */
  }
}
hydrate();

export function getState() {
  return state;
}

/** Subscribe to store changes. Returns an unsubscribe function. */
export function subscribe(cb) {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

/** The raw File chosen on the ingest screen, held in memory until uploaded. */
export function setPendingFile(file) {
  pendingFile = file;
  state = { ...state, fileName: file.name, fileSize: file.size, jobId: null, jobDone: false };
  persist();
  emit();
}
export function getPendingFile() {
  return pendingFile;
}

export function setJobId(jobId) {
  state = { ...state, jobId, jobDone: false };
  persist();
  emit();
}

export function setJobDone(done) {
  state = { ...state, jobDone: done };
  persist();
  emit();
}

export function setSubjects(subjects) {
  state = { ...state, subjects };
  persist();
  emit();
}

/**
 * Merge a fresh snapshot from the backend into the store. Names always take
 * the backend value so titles update live as the extractor refines them,
 * while local learner progress (completed, accuracy) and already-fetched
 * blocks are preserved.
 */
export function mergeSubjects(incoming) {
  const prev = state.subjects;
  const merged = incoming.map((s) => {
    const oldS = prev.find((p) => p.id === s.id);
    return {
      ...s,
      units: s.units.map((u) => {
        const oldU = oldS?.units.find((p) => p.id === u.id);
        return {
          ...u,
          topics: u.topics.map((t) => {
            const oldT = oldU?.topics.find((p) => p.id === t.id);
            return {
              ...t,
              blocks: t.blocks?.length ? t.blocks : oldT?.blocks ?? [],
              completed: oldT?.completed || t.completed,
              accuracy: oldT?.accuracy ?? t.accuracy ?? null,
            };
          }),
        };
      }),
    };
  });

  // job-sync polls every 2s while a job is running, and calls this on every
  // tick even when nothing actually changed since the last poll. Screens
  // that subscribe to the store (graph.js, arc.js) respond to every emit()
  // by tearing down and rebuilding their whole orbit DOM, including
  // restarting every node's CSS float animation from scratch - with several
  // subjects/units that's a visible stutter every 2 seconds, and nodes
  // mid-animation snapping back and restarting can look like flickering or
  // doubled icons. Skipping the update (and the emit) when the merged
  // result is identical to what's already there fixes both: screens only
  // actually redraw when the data really changed.
  if (JSON.stringify(merged) === JSON.stringify(prev)) return;

  state = { ...state, subjects: merged };
  persist();
  emit();
}

export function setTopicBlocks(topicId, blocks) {
  state = {
    ...state,
    subjects: state.subjects.map((s) => ({
      ...s,
      units: s.units.map((u) => ({
        ...u,
        topics: u.topics.map((t) => (t.id === topicId ? { ...t, blocks, status: "ready" } : t)),
      })),
    })),
  };
  persist();
  emit();
}

/**
 * Remembers which stage (theory/quiz/arrange/fill/catch/score/notes) a
 * learner was last on for a given topic, so leaving mid-topic and coming
 * back resumes there instead of always restarting from theory. Read with
 * getTopicStage(topicId) when a topic screen mounts.
 */
export function setTopicStage(topicId, stage) {
  if (!topicId || !stage) return;
  if (state.topicStages[topicId] === stage) return; // no-op if unchanged, avoid a needless emit
  state = { ...state, topicStages: { ...state.topicStages, [topicId]: stage } };
  persist();
  emit();
}

export function getTopicStage(topicId) {
  return state.topicStages?.[topicId] ?? null;
}

/** Clears a topic's remembered stage — e.g. after "New round" starts it over. */
export function clearTopicStage(topicId) {
  if (!topicId || !(topicId in (state.topicStages || {}))) return;
  const next = { ...state.topicStages };
  delete next[topicId];
  state = { ...state, topicStages: next };
  persist();
  emit();
}

export function completeTopic(topicId, accuracy) {
  state = {
    ...state,
    subjects: state.subjects.map((s) => ({
      ...s,
      units: s.units.map((u) => ({
        ...u,
        topics: u.topics.map((t) => (t.id === topicId ? { ...t, completed: true, accuracy } : t)),
      })),
    })),
  };
  persist();
  emit();
}

export function reset() {
  state = { ...initial };
  pendingFile = null;
  persist();
  emit();
}

export function findSubject(subjects, id) {
  return subjects.find((s) => s.id === id) ?? null;
}
export function findUnit(subject, id) {
  return subject?.units.find((u) => u.id === id) ?? null;
}
export function findTopic(unit, id) {
  return unit?.topics.find((t) => t.id === id) ?? null;
}
