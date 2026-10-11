import { renderShell, backButton } from "../shell.js";
import { el, clear } from "../utils.js";
import { API_BASE } from "../api.js";
import { reset, getState, subscribe } from "../store.js";
import { navigate } from "../router.js";

function statCard(label, value) {
  return el("div", { class: "stat" }, [
    el("p", { class: "stat__value tabular-nums" }, value),
    el("p", { class: "stat__label" }, label),
  ]);
}

export function renderProfile(root) {
  document.title = "Your progress — NSYA.AI";

  const page = renderShell(root, {
    active: "profile",
    width: "md",
    back: backButton("Subjects", () => navigate("/graph")),
  });

  const headSlot = el("div", { class: "profile__head" });
  const statsSlot = el("div", { class: "stat-grid" });
  const listSlot = el("div", { class: "subject-list" });
  const backendSlot = el("div", { class: "profile__backend" });

  page.appendChild(headSlot);
  page.appendChild(statsSlot);
  page.appendChild(listSlot);
  page.appendChild(
    el("div", { class: "profile__actions" }, [
      el(
        "button",
        {
          type: "button",
          class: "outline-btn",
          onclick: () => {
            reset();
            navigate("/");
          },
        },
        "Start a new syllabus",
      ),
    ]),
  );
  page.appendChild(backendSlot);

  function draw() {
    const { fileName, subjects, jobId } = getState();
    const topics = subjects.flatMap((s) => s.units.flatMap((u) => u.topics));
    const done = topics.filter((t) => t.completed);
    const avg = done.length ? Math.round(done.reduce((a, t) => a + (t.accuracy ?? 0), 0) / done.length) : 0;
    const pct = topics.length ? Math.round((done.length / topics.length) * 100) : 0;

    clear(headSlot);
    headSlot.appendChild(el("span", { class: "profile__badge tabular-nums" }, `${pct}%`));
    headSlot.appendChild(el("span", { class: "profile__filename" }, fileName ?? "No syllabus loaded"));

    clear(statsSlot);
    statsSlot.appendChild(statCard("Subjects", String(subjects.length)));
    statsSlot.appendChild(statCard("Topics completed", `${done.length}/${topics.length}`));
    statsSlot.appendChild(statCard("Average accuracy", done.length ? `${avg}%` : "—"));

    clear(listSlot);
    subjects.forEach((s) => {
      const st = s.units.flatMap((u) => u.topics);
      const sd = st.filter((t) => t.completed).length;
      listSlot.appendChild(
        el("button", { type: "button", class: "subject-row", onclick: () => navigate(`/arc/${s.id}`) }, [
          el("span", { class: "name truncate" }, s.name),
          el("span", { class: "count tabular-nums" }, `${sd}/${st.length} topics`),
        ]),
      );
    });
    if (subjects.length === 0) {
      listSlot.appendChild(
        el("p", { class: "pipeline__empty" }, "Nothing loaded yet — upload a syllabus to get started."),
      );
    }

    clear(backendSlot);
    backendSlot.appendChild(document.createTextNode("Backend: "));
    backendSlot.appendChild(el("code", {}, API_BASE));
    if (jobId) {
      backendSlot.appendChild(document.createTextNode(" · job "));
      backendSlot.appendChild(el("code", {}, jobId));
    }
  }

  draw();
  const unsub = subscribe(draw);
  return () => unsub();
}
