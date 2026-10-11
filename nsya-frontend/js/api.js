/**
 * NSYA.AI backend client.
 *
 * Every function here maps 1:1 to an endpoint your Python backend
 * (FastAPI / Flask / Django) must expose. Nothing here is mocked.
 *
 * Point the app at your server by editing API_BASE below, or by setting
 * `window.NSYA_API_URL` before this script loads (e.g. from a small inline
 * <script> in index.html, or a config.js you swap per environment).
 *
 * See docs/backend-api.md (copied into this folder) for the exact
 * request/response contract — it is unchanged from the original app.
 */

export const API_BASE = (window.NSYA_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request(path, init) {
  let res;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      headers: { Accept: "application/json", ...(init?.headers ?? {}) },
      ...init,
    });
  } catch {
    throw new ApiError(`Cannot reach the backend at ${API_BASE}. Is your Python server running?`, 0);
  }
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new ApiError(text || `${res.status} ${res.statusText}`, res.status);
  }
  return res.json();
}

/* ---------------- ingestion ---------------- */

/** POST {base}/syllabus/upload — multipart: `file`. Resolves { jobId }. */
export function uploadSyllabus(file, onProgress, signal) {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", file);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/syllabus/upload`);
    xhr.responseType = "json";

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) {
        onProgress(Math.round((e.loaded / e.total) * 100));
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        const body = xhr.response;
        const jobId = body?.jobId ?? body?.job_id;
        if (!jobId) {
          reject(new ApiError("Upload response did not include a jobId", 500));
          return;
        }
        onProgress?.(100);
        resolve({ jobId });
      } else {
        reject(new ApiError(xhr.statusText || "Upload failed", xhr.status));
      }
    };
    xhr.onerror = () =>
      reject(new ApiError(`Cannot reach the backend at ${API_BASE}. Is your Python server running?`, 0));
    xhr.onabort = () => reject(new ApiError("Upload cancelled", 0));
    signal?.addEventListener("abort", () => xhr.abort());
    xhr.send(form);
  });
}

/** GET {base}/jobs/{jobId} */
export function getJob(jobId) {
  return request(`/jobs/${encodeURIComponent(jobId)}`);
}

/* ---------------- lesson content ---------------- */

/**
 * GET {base}/topics/{topicId}?regenerate=true
 * Pass regenerate: true (only from the explicit "New round" action) to
 * force the backend to produce genuinely fresh content, bypassing its
 * cache. A normal call with no options just returns the cached lesson.
 * The response's "image" key is present only when a real image was
 * actually found during generation - never a placeholder.
 */
export function getTopicContent(topicId, { regenerate = false } = {}) {
  const q = regenerate ? "?regenerate=true" : "";
  return request(`/topics/${encodeURIComponent(topicId)}${q}`);
}

export function postTopicResult(topicId, accuracy) {
  return request(`/topics/${encodeURIComponent(topicId)}/complete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ accuracy }),
  }).catch(() => undefined);
}

/**
 * GET {base}/topics/{topicId}/subtopics
 * Small child-node list for a topic: id/title/order only, for rendering
 * a topic as a parent node with its subtopics as small child nodes.
 */
export function getSubtopics(topicId) {
  return request(`/topics/${encodeURIComponent(topicId)}/subtopics`);
}

/**
 * GET {base}/subtopics/{subtopicId}
 * One subtopic's full learning content, plus its parent topic/unit/
 * subject context.
 */
export function getSubtopicContent(subtopicId) {
  return request(`/subtopics/${encodeURIComponent(subtopicId)}`);
}

/**
 * GET {base}/topics/{topicId}/explainability
 * Small "how was this made" panel data - which provider generated the
 * lesson, whether RAG kicked in, and which source chunks it pulled from.
 * Purely informational, never blocks or changes the actual lesson.
 */
export function getTopicExplainability(topicId) {
  return request(`/topics/${encodeURIComponent(topicId)}/explainability`).catch(() => ({ available: false }));
}

/**
 * GET {base}/subjects/{subjectId}/sources
 * Lists extra reference docs uploaded for a subject (max 2, separate from
 * the main syllabus upload).
 */
export function getSubjectSources(subjectId) {
  return request(`/subjects/${encodeURIComponent(subjectId)}/sources`).catch(() => ({ count: 0, max: 2, sources: [] }));
}

/**
 * POST {base}/subjects/{subjectId}/sources
 * Uploads one extra reference doc for a subject. Rejects past the 2-doc cap.
 */
export async function uploadSubjectSource(subjectId, file) {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/subjects/${encodeURIComponent(subjectId)}/sources`, {
    method: "POST",
    body: form,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new ApiError(data.detail || "Could not upload this file", res.status);
  }
  return data;
}

/**
 * GET {base}/api/v1/knowledge/{syllabusId}/roadmap/{subjectId}
 * The knowledge-graph-derived learning order for one subject: each topic's
 * step number and what it depends on. Used by the Explainable AI panel to
 * show the topic graph for the unit currently being viewed.
 */
export function getRoadmap(syllabusId, subjectId) {
  return request(`/api/v1/knowledge/${encodeURIComponent(syllabusId)}/roadmap/${encodeURIComponent(subjectId)}`).catch(() => null);
}
