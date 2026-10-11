import { renderShell, backButton } from "../shell.js";
import { el } from "../utils.js";
import { Icon } from "../icons.js";
import { getState, subscribe, findSubject } from "../store.js";
import { useJobSync } from "../job-sync.js";
import { navigate } from "../router.js";
import { getSubjectSources, uploadSubjectSource } from "../api.js";

const SVG_NS = "http://www.w3.org/2000/svg";

export function renderArc(root, { subjectId }) {
  document.title = "Units arc — NSYA.AI";

  let offset = 0;
  let redirectTimer = null;

  if (getState().subjects.length === 0) {
    navigate("/");
    return;
  }

  const subject = findSubject(getState().subjects, subjectId);
  if (!subject) {
    navigate("/graph");
    return;
  }

  const page = renderShell(root, {
    subjectId: subject.id,
    active: "units",
    width: "lg",
    title: subject.name,
    subtitle: `Scroll to rotate the arc · ${subject.units.length} units`,
    back: backButton("Subjects", () => navigate("/graph")),
  });

  const wrap = el("div", { class: "arc-wrap" });
  page.appendChild(wrap);

  // small, tucked-away control for uploading extra reference docs for this
  // subject (max 2, separate from the main syllabus). doesn't touch the
  // arc navigation above it at all - purely optional, corner-only
  renderSourcesCorner(page, subject.id);

  function draw() {
    const s = findSubject(getState().subjects, subjectId);
    if (!s) return;

    wrap.innerHTML = "";
    const units = s.units;
    const n = units.length;
    const span = 150;
    const step = n > 1 ? span / (n - 1) : 0;

    const orbit = el("div", { class: "arc-orbit" });
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 100 100");
    svg.setAttribute("aria-hidden", "true");
    const guide = document.createElementNS(SVG_NS, "path");
    guide.setAttribute("d", "M 12 78 A 46 42 0 0 1 88 78");
    guide.setAttribute("fill", "none");
    guide.setAttribute("stroke", "var(--shape)");
    guide.setAttribute("stroke-width", "0.8");
    guide.setAttribute("stroke-dasharray", "2 2");
    svg.appendChild(guide);
    orbit.appendChild(svg);

    units.forEach((u, i) => {
      const deg = -span / 2 + i * step + offset;
      const rad = (deg * Math.PI) / 180;
      const R = 42;
      const x = 50 + Math.sin(rad) * R;
      const y = 54 - Math.cos(rad) * R * 0.9;
      const near = Math.abs(((deg + 540) % 360) - 180) > 120;

      const node = el(
        "button",
        {
          type: "button",
          class: "arc-node",
          style: `left:${x}%;top:${y}%;opacity:${near ? 1 : 0.35};transform:translate(-50%,-50%) scale(${
            near ? 1 : 0.82
          })`,
          onclick: () => navigate(`/pipeline/${s.id}/${u.id}`),
        },
        [
          el("span", { class: "arc-node__circle tabular-nums" }, String(u.number)),
          el("span", { class: "arc-node__name line-clamp-2" }, u.name),
        ],
      );
      orbit.appendChild(node);
    });

    wrap.appendChild(orbit);
  }

  draw();
  const unsub = subscribe(draw);
  const stopSync = useJobSync();

  function onWheel(e) {
    e.preventDefault();
    offset += e.deltaY * 0.12;
    draw();
  }
  window.addEventListener("wheel", onWheel, { passive: false });

  if (getState().subjects.length === 0) redirectTimer = setTimeout(() => navigate("/"), 0);

  return () => {
    unsub();
    stopSync();
    window.removeEventListener("wheel", onWheel);
    clearTimeout(redirectTimer);
  };
}

function renderSourcesCorner(page, subjectId) {
  const btn = el(
    "button",
    { type: "button", class: "sources-corner-btn", "aria-label": "Reference sources for this subject" },
    [el("span", { html: Icon.bookOpen("", 15) }), el("span", { class: "sources-corner-btn__count" }, "")],
  );
  page.appendChild(btn);

  let panel = null;

  function closePanel() {
    if (panel) {
      panel.remove();
      panel = null;
    }
    document.removeEventListener("click", onOutsideClick);
  }

  function onOutsideClick(e) {
    if (panel && !panel.contains(e.target) && e.target !== btn && !btn.contains(e.target)) closePanel();
  }

  async function refreshCount() {
    const info = await getSubjectSources(subjectId).catch(() => ({ count: 0, max: 2 }));
    btn.querySelector(".sources-corner-btn__count").textContent = `${info.count}/${info.max}`;
    return info;
  }

  async function openPanel() {
    if (panel) {
      closePanel();
      return;
    }
    panel = el("div", { class: "sources-panel" }, [el("p", { class: "sources-panel__loading" }, "Loading…")]);
    page.appendChild(panel);
    setTimeout(() => document.addEventListener("click", onOutsideClick), 0);

    const info = await getSubjectSources(subjectId).catch(() => ({ count: 0, max: 2, sources: [] }));
    if (!panel) return;

    panel.innerHTML = "";
    panel.appendChild(el("p", { class: "sources-panel__title" }, "Reference sources"));
    panel.appendChild(
      el(
        "p",
        { class: "sources-panel__hint" },
        "Optional extra material (a textbook chapter, notes) to ground this subject's lessons. Doesn't affect the main syllabus.",
      ),
    );

    if (info.sources?.length) {
      const list = el("ul", { class: "sources-panel__list" });
      info.sources.forEach((s) => {
        list.appendChild(el("li", { class: "sources-panel__item" }, s.filename));
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
          closePanel();
        } catch (e) {
          uploadBtn.textContent = e instanceof Error ? e.message : "Upload failed";
          uploadBtn.disabled = false;
        }
      });
      panel.appendChild(uploadBtn);
      panel.appendChild(fileInput);
    } else {
      panel.appendChild(el("p", { class: "sources-panel__hint" }, "Max reached for this subject."));
    }
  }

  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    openPanel();
  });

  refreshCount();
}
