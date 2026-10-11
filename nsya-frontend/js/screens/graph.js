import { renderShell, backButton } from "../shell.js";
import { el } from "../utils.js";
import { getState, subscribe } from "../store.js";
import { useJobSync } from "../job-sync.js";
import { navigate } from "../router.js";
import { attachSubjectSourceBadge } from "../sources-panel.js";

const SVG_NS = "http://www.w3.org/2000/svg";

export function renderGraph(root) {
  document.title = "Subjects graph — NSYA.AI";

  let { subjects } = getState();
  let redirectTimer = null;

  const page = renderShell(root, {
    active: "subjects",
    width: "lg",
    title: `${subjects.length} subjects extracted`,
    subtitle: "Choose a subject to open its units",
    back: backButton("Upload", () => navigate("/")),
  });

  const wrap = el("div", { class: "graph-wrap" });
  page.appendChild(wrap);

  function draw() {
    subjects = getState().subjects;
    page.querySelector(".page__title").textContent = `${subjects.length} subjects extracted`;

    wrap.innerHTML = "";
    const n = Math.max(subjects.length, 1);
    const orbit = el("div", { class: "graph-orbit" });

    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 100 100");
    svg.setAttribute("aria-hidden", "true");
    subjects.forEach((s, i) => {
      const a1 = (i / n) * Math.PI * 2 - Math.PI / 2;
      const a2 = ((i + 1) / n) * Math.PI * 2 - Math.PI / 2;
      const path = document.createElementNS(SVG_NS, "path");
      path.setAttribute(
        "d",
        `M ${50 + Math.cos(a1) * 38} ${50 + Math.sin(a1) * 38} A 40 40 0 0 1 ${50 + Math.cos(a2) * 38} ${
          50 + Math.sin(a2) * 38
        }`,
      );
      path.setAttribute("fill", "none");
      path.setAttribute("stroke", "var(--shape)");
      path.setAttribute("stroke-width", "1.2");
      path.setAttribute("stroke-linecap", "round");
      svg.appendChild(path);
    });
    orbit.appendChild(svg);

    subjects.forEach((s, i) => {
      const angle = (i / n) * Math.PI * 2 - Math.PI / 2;
      const x = 50 + Math.cos(angle) * 38;
      const y = 50 + Math.sin(angle) * 38;
      const circle = el("span", { class: "graph-node__circle" }, [
        el("span", { class: "graph-node__count tabular-nums" }, String(i + 1)),
        el("span", { class: "graph-node__unitlabel" }, `${s.units.length} unit${s.units.length === 1 ? "" : "s"}`),
      ]);

      const node = el(
        "button",
        {
          type: "button",
          class: "graph-node",
          style: `left:${x}%;top:${y}%`,
          onclick: () => navigate(`/arc/${s.id}`),
        },
        [circle, el("span", { class: "graph-node__name line-clamp-2" }, s.name)],
      );
      orbit.appendChild(node);

      // Per-subject icon: upload your own resource (textbook chapter, notes,
      // past papers) for THIS subject specifically, right from the subject
      // list - no need to open the subject first. Feeds the same RAG +
      // Explainable AI + quiz-generation pipeline every reference source
      // does (see sources-panel.js for the full flow).
      attachSubjectSourceBadge(circle, s.id, s.name);
    });

    wrap.appendChild(orbit);
  }

  draw();
  const unsub = subscribe(draw);
  const stopSync = useJobSync();

  if (subjects.length === 0) {
    redirectTimer = setTimeout(() => navigate("/"), 400);
  }

  return () => {
    unsub();
    stopSync();
    clearTimeout(redirectTimer);
  };
}
