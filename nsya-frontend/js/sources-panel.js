import { el, clear, toast } from "./utils.js";
import { Icon } from "./icons.js";
import { getSubjectSources, uploadSubjectSource } from "./api.js";

/**
 * Per-subject "upload your own resource" badge + floating panel.
 *
 * This is the same reference-source upload flow the arc screen and the
 * Explainable AI drawer already have (backend: /subjects/{id}/sources,
 * max 2 per subject, FAISS-indexed for retrieval), just packaged as one
 * small icon that can be dropped onto ANY per-subject UI element - here,
 * directly onto each subject's node on the subjects graph, so uploading a
 * resource doesn't require first navigating into that subject.
 *
 * Uses fixed positioning anchored to the badge's own screen position
 * (not to a page-level container), so it works regardless of where the
 * badge lives - including nodes that rotate/reflow, like the graph orbit.
 *
 * Once a file is uploaded here it flows through the exact same pipeline
 * every other reference source does: chunked + embedded into that
 * subject's FAISS index (app/services/embeddings.py), then pulled into
 * context by generate_topic_lesson() the next time a topic in this
 * subject is generated (first visit, or an explicit "New round"/regenerate
 * for a topic that was already generated before the upload) - and the
 * chunks it actually used show up, with a link back to this file, in that
 * topic's Explainable AI panel and in the quiz/exercises generated
 * alongside the lesson.
 */
export function attachSubjectSourceBadge(hostEl, subjectId, subjectName) {
  // Deliberately a <span role="button">, not a real <button>: hostEl (the
  // subject's circle) commonly sits inside the subject's own <button> (the
  // clickable node that navigates into it), and nesting a real <button>
  // inside another <button> is invalid HTML that browsers render
  // inconsistently. A span with button semantics + keyboard support gets
  // the same click/keyboard behavior without that problem.
  const badge = el(
    "span",
    {
      role: "button",
      tabindex: "0",
      class: "graph-node__source-btn",
      "aria-label": `Upload your own resource for ${subjectName || "this subject"}`,
      title: `Upload your own resource for ${subjectName || "this subject"}`,
    },
    [el("span", { html: Icon.uploadCloud("", 12) }), el("span", { class: "graph-node__source-btn__count" }, "")],
  );
  hostEl.appendChild(badge);

  let panel = null;

  function closePanel() {
    if (panel) {
      panel.remove();
      panel = null;
    }
    document.removeEventListener("click", onOutsideClick);
    window.removeEventListener("scroll", closePanel, true);
    window.removeEventListener("resize", closePanel);
  }

  function onOutsideClick(e) {
    if (panel && !panel.contains(e.target) && e.target !== badge && !badge.contains(e.target)) closePanel();
  }

  function positionPanel() {
    if (!panel) return;
    const rect = badge.getBoundingClientRect();
    const width = Math.min(300, window.innerWidth - 32);
    let left = rect.left + rect.width / 2 - width / 2;
    left = Math.max(16, Math.min(left, window.innerWidth - width - 16));
    let top = rect.bottom + 10;
    const estimatedHeight = 260;
    if (top + estimatedHeight > window.innerHeight) top = Math.max(16, rect.top - estimatedHeight - 10);
    panel.style.left = `${left}px`;
    panel.style.top = `${top}px`;
    panel.style.width = `${width}px`;
  }

  async function refreshCount() {
    const info = await getSubjectSources(subjectId).catch(() => ({ count: 0, max: 2 }));
    badge.querySelector(".graph-node__source-btn__count").textContent = `${info.count}/${info.max}`;
    return info;
  }

  async function openPanel() {
    if (panel) {
      closePanel();
      return;
    }
    panel = el("div", { class: "sources-panel sources-panel--floating" }, [
      el("p", { class: "sources-panel__loading" }, "Loading…"),
    ]);
    document.body.appendChild(panel);
    positionPanel();
    setTimeout(() => {
      document.addEventListener("click", onOutsideClick);
      window.addEventListener("scroll", closePanel, true);
      window.addEventListener("resize", closePanel);
    }, 0);

    const info = await getSubjectSources(subjectId).catch(() => ({ count: 0, max: 2, sources: [] }));
    if (!panel) return;

    clear(panel);
    panel.appendChild(
      el("p", { class: "sources-panel__title" }, `Reference sources — ${subjectName || subjectId}`),
    );
    panel.appendChild(
      el(
        "p",
        { class: "sources-panel__hint" },
        "Upload your own material for this subject (a textbook chapter, notes, past papers). It's indexed for retrieval and used to ground this subject's lessons, quizzes, and the Explainable AI panel — alongside the main syllabus.",
      ),
    );

    if (info.sources?.length) {
      const list = el("ul", { class: "sources-panel__list" });
      info.sources.forEach((s) => {
        list.appendChild(
          el("li", { class: "sources-panel__item" }, [
            el("span", { class: "truncate" }, s.filename),
            el(
              "span",
              { class: "sources-panel__item-meta" },
              s.chunks_ingested ? ` · ${s.chunks_ingested} chunks indexed` : " · indexing…",
            ),
          ]),
        );
      });
      panel.appendChild(list);
    } else {
      panel.appendChild(el("p", { class: "sources-panel__hint" }, "None uploaded yet."));
    }

    if (info.count < info.max) {
      const fileInput = el("input", { type: "file", accept: ".pdf,.txt,.png,.jpg,.jpeg", style: "display:none" });
      const uploadBtn = el(
        "button",
        { type: "button", class: "sources-panel__upload-btn" },
        `Add source (${info.count}/${info.max})`,
      );
      uploadBtn.addEventListener("click", () => fileInput.click());
      fileInput.addEventListener("change", async () => {
        const file = fileInput.files?.[0];
        if (!file) return;
        uploadBtn.textContent = "Uploading…";
        uploadBtn.disabled = true;
        try {
          await uploadSubjectSource(subjectId, file);
          await refreshCount();
          toast(`Added "${file.name}" — topics you open next in ${subjectName || "this subject"} will use it.`);
          closePanel();
        } catch (e) {
          uploadBtn.textContent = e instanceof Error ? e.message : "Upload failed";
          uploadBtn.disabled = false;
        }
      });
      panel.appendChild(uploadBtn);
      panel.appendChild(fileInput);
      panel.appendChild(
        el(
          "p",
          { class: "sources-panel__note" },
          "Note: a topic you've already opened keeps its cached lesson until you use \"New round\" on it — that's what picks up a newly added source.",
        ),
      );
    } else {
      panel.appendChild(el("p", { class: "sources-panel__hint" }, "Max reached for this subject."));
    }
  }

  badge.addEventListener("click", (e) => {
    e.stopPropagation();
    e.preventDefault();
    openPanel();
  });
  badge.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.stopPropagation();
      e.preventDefault();
      openPanel();
    }
  });

  refreshCount();

  return badge;
}
