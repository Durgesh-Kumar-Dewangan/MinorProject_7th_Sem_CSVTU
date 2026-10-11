import { renderShell, backButton } from "../shell.js";
import { Icon } from "../icons.js";
import { el, clear } from "../utils.js";
import { getJob } from "../api.js";
import { mergeSubjects, setJobDone, setSubjects, getState } from "../store.js";
import { navigate } from "../router.js";

const ORDER = ["extract", "distribute", "generate", "done"];

function stepRow(label, state) {
  return el("div", { class: "step" }, [
    el("span", { class: `step__dot ${state === "running" ? "is-running" : ""} ${state === "done" ? "is-done" : ""}` }, [
      state === "done" ? el("span", { html: Icon.check("", 12) }) : null,
    ]),
    el("span", { class: `step__label ${state !== "idle" ? "is-active" : ""}` }, label),
  ]);
}

export function renderExtracting(root) {
  document.title = "Extracting syllabus — NSYA.AI";

  const { fileName, jobId } = getState();
  if (!jobId) {
    navigate("/");
    return;
  }

  let alive = true;
  let timer = null;
  let job = null;
  let error = null;
  let lastSnapshot = null; // used to skip redundant redraws, see poll() below

  const page = renderShell(root, {
    active: "upload",
    center: true,
    width: "lg",
    title: "Processing your syllabus",
    subtitle: fileName || undefined,
    back: backButton("Upload", () => navigate("/uploading")),
  });

  const ringSlot = el("div", { class: "extract-ring" });
  const stepsSlot = el("div", { class: "" });
  const errorSlot = el("div", {});
  const foundSlot = el("div", {});
  const rightCol = el("div", { class: "" }, [stepsSlot, errorSlot, foundSlot]);
  page.appendChild(el("div", { class: "extract-grid" }, [ringSlot, rightCol]));

  function draw() {
    const phase = job?.phase ?? "extract";
    const found = job?.subjects ?? [];
    const idx = ORDER.indexOf(phase);
    const running = job?.status !== "done" && job?.status !== "error";

    const stateOf = (p) => {
      const i = ORDER.indexOf(p);
      if (i < idx) return "done";
      if (i === idx) return running ? "running" : "done";
      return "idle";
    };

    clear(ringSlot);
    if (running && !error) {
      ringSlot.appendChild(el("div", { class: "extract-ring__outer nsya-ring-outer" }));
      ringSlot.appendChild(el("div", { class: "extract-ring__inner nsya-ring-inner" }));
      ringSlot.appendChild(
        el("div", { class: "extract-ring__label" }, [
          el("p", { class: "extract-ring__phase" }, phase),
          el("p", { class: "extract-ring__progress" }, `${job?.progress ?? 0}%`),
        ]),
      );
    } else {
      ringSlot.appendChild(el("div", { class: "extract-ring__track" }));
      ringSlot.appendChild(
        el("div", { class: `extract-ring__done nsya-rise ${error ? "is-error" : ""}` }, [
          error ? el("span", { html: Icon.alertCircle("", 34) }) : el("span", { html: Icon.check("", 34) }),
        ]),
      );
    }

    clear(stepsSlot);
    stepsSlot.appendChild(stepRow("Extract syllabus", stateOf("extract")));
    stepsSlot.appendChild(stepRow("Distribute into subjects", stateOf("distribute")));
    stepsSlot.appendChild(stepRow("Generate learning tracks", stateOf("generate")));

    clear(errorSlot);
    if (error) {
      errorSlot.appendChild(
        el("div", { class: "extract-error" }, [
          error,
          el("button", { type: "button", onclick: () => navigate("/") }, "Start over"),
        ]),
      );
    }

    clear(foundSlot);
    if (found.length) {
      const ul = el("ul", { class: "subject-found-list" });
      found.forEach((s, i) => {
        ul.appendChild(
          el("li", { class: "nsya-rise" }, [
            el("span", { class: "idx" }, String(i + 1)),
            el("span", { class: "name truncate" }, s.name),
            el("span", { class: "units" }, `${s.units.length} units`),
          ]),
        );
      });
      foundSlot.appendChild(ul);
    }
  }

  async function poll() {
    try {
      const next = await getJob(jobId);
      if (!alive) return;
      job = next;
      error = next.error ?? null;
      if (next.subjects?.length) mergeSubjects(next.subjects);
      if (next.status === "done") {
        if (next.subjects?.length) mergeSubjects(next.subjects);
        else setSubjects([]);
        setJobDone(true);
        draw();
        setTimeout(() => navigate("/graph"), 700);
        return;
      }
      if (next.status === "error") {
        setJobDone(true);
        draw();
        return;
      }
    } catch (e) {
      if (!alive) return;
      error = e instanceof Error ? e.message : "Could not reach the backend";
    }

    // Skip the redraw entirely if nothing about the job actually changed
    // since the last poll — this screen used to rebuild all its DOM (step
    // rows, found-subjects list, progress ring) every 1.2s regardless of
    // whether the backend had actually moved forward, which is the main
    // source of visible lag on this page for anything that takes more than
    // a couple poll cycles to finish processing.
    const snapshot = JSON.stringify({ phase: job?.phase, progress: job?.progress, status: job?.status, error, subjects: job?.subjects });
    if (snapshot !== lastSnapshot) {
      lastSnapshot = snapshot;
      draw();
    }

    if (alive) timer = setTimeout(poll, 1200);
  }

  draw();
  poll();

  return () => {
    alive = false;
    clearTimeout(timer);
  };
}
