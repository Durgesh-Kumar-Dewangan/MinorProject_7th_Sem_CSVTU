import { el, clear } from "./utils.js";
import { renderTrustReport } from "./xai-metrics.js";
import { Icon } from "./icons.js";
import {
  getSubjectSources,
  uploadSubjectSource,
  getRoadmap,
  getTopicExplainability,
  API_BASE,
} from "./api.js";

/**
 * Explainable AI side overlay - a slide-in drawer scoped to whatever unit
 * the learner is currently viewing. Three sections:
 *   1. Reference sources  - upload/list extra docs for this SUBJECT (max 2,
 *      separate from the main syllabus), same backend this app already had.
 *   2. Topic graph         - this subject's knowledge-graph-derived learning
 *      order (step number + prerequisite), pulled from the roadmap endpoint,
 *      filtered down to just the topics in the current unit.
 *   3. Generated content   - for each topic in this unit: which provider
 *      wrote it (or "template"), whether real retrieval was used, and a
 *      real link to whichever source document it actually pulled from.
 *
 * Call openExplainableAI({ subjectId, unitId, unit, syllabusId }) to open
 * it. Returns a close() function. Only one instance is ever open at a time
 * - opening a second one closes the first.
 */

let currentClose = null;

export function renderExplainableAITrigger({ subjectId, unitId, unit, syllabusId }) {
  const btn = el(
    "button",
    { type: "button", class: "xai-trigger-btn", "aria-label": "Explainable AI" },
    [el("span", { html: Icon.sparkles("", 15) }), el("span", {}, "Explainable AI")],
  );
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    openExplainableAI({ subjectId, unitId, unit, syllabusId });
  });
  return btn;
}

function openExplainableAI({ subjectId, unitId, unit, syllabusId }) {
  if (currentClose) {
    currentClose();
  }

  const overlay = el("div", { class: "xai-overlay" });
  const panel = el("aside", { class: "xai-drawer", role: "dialog", "aria-label": "Explainable AI" });
  overlay.appendChild(panel);
  document.body.appendChild(overlay);
  document.body.style.overflow = "hidden";

  function close() {
    overlay.remove();
    document.body.style.overflow = "";
    document.removeEventListener("keydown", onKeydown);
    if (currentClose === close) currentClose = null;
  }
  currentClose = close;

  function onKeydown(e) {
    if (e.key === "Escape") close();
  }
  document.addEventListener("keydown", onKeydown);
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) close();
  });

  panel.appendChild(
    el("header", { class: "xai-drawer__header" }, [
      el("div", {}, [
        el("span", { class: "xai-drawer__eyebrow" }, [el("span", { html: Icon.sparkles("", 13) }), " Explainable AI"]),
        el("h2", { class: "xai-drawer__title" }, unit?.name || "This unit"),
      ]),
      el(
        "button",
        { type: "button", class: "xai-drawer__close", "aria-label": "Close", onclick: close },
        "×",
      ),
    ]),
  );

  const body = el("div", { class: "xai-drawer__body" });
  panel.appendChild(body);

  renderSourcesSection(body, subjectId);
  renderTopicGraphSection(body, syllabusId, subjectId, unit);
  renderExplainabilitySection(body, unit);
}

function sectionShell(body, title, iconFn) {
  const section = el("section", { class: "xai-section" }, [
    el("h3", { class: "xai-section__title" }, [el("span", { html: iconFn("", 14) }), " " + title]),
  ]);
  body.appendChild(section);
  return section;
}

/* ---------------- 1. Reference sources (per subject) ---------------- */

function renderSourcesSection(body, subjectId) {
  const section = sectionShell(body, "Reference sources", Icon.bookOpen);
  section.appendChild(
    el(
      "p",
      { class: "xai-section__hint" },
      "Optional extra material (a textbook chapter, notes) to ground this subject's lessons — separate from the main syllabus.",
    ),
  );

  const listEl = el("ul", { class: "xai-sources-list" }, [el("li", { class: "xai-section__hint" }, "Loading…")]);
  section.appendChild(listEl);

  const uploadRow = el("div", { class: "xai-sources-upload" });
  section.appendChild(uploadRow);

  async function refresh() {
    const info = await getSubjectSources(subjectId).catch(() => ({ count: 0, max: 2, sources: [] }));
    clear(listEl);
    if (info.sources?.length) {
      info.sources.forEach((s) => {
        listEl.appendChild(
          el("li", { class: "xai-sources-list__item" }, [
            el("span", { html: Icon.fileText("", 14) }),
            el("span", { class: "truncate" }, s.filename),
            el("span", { class: "xai-sources-list__meta" }, s.chunks_ingested ? `${s.chunks_ingested} chunks indexed` : "not indexed yet"),
          ]),
        );
      });
    } else {
      clear(listEl);
      listEl.appendChild(el("li", { class: "xai-section__hint" }, "None uploaded yet."));
    }

    clear(uploadRow);
    if (info.count < info.max) {
      const fileInput = el("input", { type: "file", accept: ".pdf,.txt,.png,.jpg,.jpeg", style: "display:none" });
      const uploadBtn = el("button", { type: "button", class: "xai-upload-btn" }, `Add source (${info.count}/${info.max})`);
      uploadBtn.addEventListener("click", () => fileInput.click());
      fileInput.addEventListener("change", async () => {
        const file = fileInput.files?.[0];
        if (!file) return;
        uploadBtn.textContent = "Uploading…";
        uploadBtn.disabled = true;
        try {
          await uploadSubjectSource(subjectId, file);
          await refresh();
        } catch (e) {
          uploadBtn.textContent = e instanceof Error ? e.message : "Upload failed";
          uploadBtn.disabled = false;
        }
      });
      uploadRow.appendChild(uploadBtn);
      uploadRow.appendChild(fileInput);
    } else {
      uploadRow.appendChild(el("p", { class: "xai-section__hint" }, "Max reached for this subject."));
    }
  }

  refresh();
}

/* ---------------- 2. Topic graph (this unit's slice of the roadmap) ---------------- */

async function renderTopicGraphSection(body, syllabusId, subjectId, unit) {
  const section = sectionShell(body, "Topic graph", Icon.listTree);
  section.appendChild(el("p", { class: "xai-section__hint" }, "Learning order for this unit, from the knowledge graph."));

  const listEl = el("ol", { class: "xai-graph-list" }, [el("li", { class: "xai-section__hint" }, "Loading…")]);
  section.appendChild(listEl);

  if (!syllabusId) {
    clear(listEl);
    listEl.appendChild(el("li", { class: "xai-section__hint" }, "Not available yet."));
    return;
  }

  const roadmap = await getRoadmap(syllabusId, subjectId);
  clear(listEl);

  const unitTopicIds = new Set((unit?.topics || []).map((t) => t.id));
  const steps = (roadmap?.roadmap || []).filter((s) => s.type === "topic" && unitTopicIds.has(s.node_key));

  if (!steps.length) {
    listEl.appendChild(el("li", { class: "xai-section__hint" }, "No graph data available for this unit yet."));
    return;
  }

  steps.forEach((step) => {
    listEl.appendChild(
      el("li", { class: "xai-graph-list__item" }, [
        el("span", { class: "xai-graph-list__step tabular-nums" }, String(step.order ?? "")),
        el("span", { class: "xai-graph-list__title" }, step.title || step.node_key),
      ]),
    );
  });
}

/* ---------------- 3. Explainability per topic in this unit ---------------- */

async function renderExplainabilitySection(body, unit) {
  const section = sectionShell(body, "Generated content", Icon.sparkles);
  section.appendChild(el("p", { class: "xai-section__hint" }, "How each topic in this unit was actually generated."));

  const listEl = el("div", { class: "xai-explain-list" });
  section.appendChild(listEl);

  const topics = unit?.topics || [];
  if (!topics.length) {
    listEl.appendChild(el("p", { class: "xai-section__hint" }, "This unit has no topics yet."));
    return;
  }

  for (const topic of topics) {
    const row = el("div", { class: "xai-explain-item" }, [
      el("p", { class: "xai-explain-item__title" }, topic.name),
      el("p", { class: "xai-section__hint" }, "Loading…"),
    ]);
    listEl.appendChild(row);

    getTopicExplainability(topic.id).then((info) => {
      clear(row);
      row.appendChild(el("p", { class: "xai-explain-item__title" }, topic.name));

      if (!info?.available) {
        row.appendChild(el("p", { class: "xai-section__hint" }, "Not generated yet — opens on first visit."));
        return;
      }

      const providerLabel = info.generated_by === "template" ? "Template (no AI configured)" : info.generated_by;
      row.appendChild(
        el("p", { class: "xai-explain-item__meta" }, [
          el("span", { class: `xai-badge ${info.retrieval_used ? "xai-badge--rag" : ""}` }, providerLabel),
          info.retrieval_used ? el("span", { class: "xai-badge xai-badge--rag" }, "Retrieval-grounded") : null,
        ]),
      );

      // Phase 4 + 5 report (trust score, validation, hybrid retrieval,
      // attribution, SHAP, evidence tracing) - shared with the lesson popup.
      row.appendChild(renderTrustReport(info));
    });
  }
}
