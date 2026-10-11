import { renderShell, backButton } from "../shell.js";
import { Icon } from "../icons.js";
import { el, clear } from "../utils.js";
import { getState, subscribe, findSubject, findUnit } from "../store.js";
import { useJobSync } from "../job-sync.js";
import { navigate } from "../router.js";
import { renderExplainableAITrigger } from "../xai-panel.js";

export function renderPipeline(root, { subjectId, unitId }) {
  document.title = "Topic pipeline — NSYA.AI";

  if (getState().subjects.length === 0) {
    navigate("/");
    return;
  }
  const subject0 = findSubject(getState().subjects, subjectId);
  const unit0 = findUnit(subject0, unitId);
  if (!subject0 || !unit0) {
    navigate("/graph");
    return;
  }

  const page = renderShell(root, {
    subjectId,
    unitId,
    active: "topics",
    width: "md",
    title: `Unit ${unit0.number} · ${unit0.name}`,
    subtitle: subtitleFor(unit0.topics),
    back: backButton("Units", () => navigate(`/arc/${subjectId}`)),
  });

  const listWrap = el("div", { class: "pipeline" }, [
    el("span", { class: "pipeline__spine" }),
    el("ul", { class: "pipeline__list" }),
  ]);
  page.appendChild(listWrap);
  const list = listWrap.querySelector(".pipeline__list");

  // "Explainable AI" for this whole unit: which provider generated each
  // topic, whether retrieval fired, groundedness/faithfulness score bars,
  // feature attribution across sources, plus this unit's reference sources
  // and knowledge-graph learning order. jobId doubles as syllabusId here -
  // /syllabus/upload literally returns str(syllabus.id) as "jobId" (see
  // syllabus.py), and this app tracks one syllabus/job globally in the
  // store (job-sync.js does the same lookup), so it's the right id to pass.
  // Rebuilt on every draw() (not just once) so it always reflects the
  // unit's current topic list, not whatever it was when the page first
  // opened - topics can still be generating in the background via job-sync.
  const xaiTriggerWrap = el("div", { class: "pipeline__xai-trigger" });
  page.appendChild(xaiTriggerWrap);

  function subtitleFor(topics) {
    const doneCount = topics.filter((t) => t.completed).length;
    const generating = topics.filter((t) => t.status && t.status !== "ready").length;
    return generating
      ? `${doneCount} of ${topics.length} completed · ${generating} still generating`
      : `${doneCount} of ${topics.length} topics completed`;
  }

  function draw() {
    const subject = findSubject(getState().subjects, subjectId);
    const unit = findUnit(subject, unitId);
    if (!subject || !unit) return;

    page.querySelector(".page__title").textContent = `Unit ${unit.number} · ${unit.name}`;
    page.querySelector(".page__subtitle").textContent = subtitleFor(unit.topics);

    clear(xaiTriggerWrap);
    xaiTriggerWrap.appendChild(
      renderExplainableAITrigger({ subjectId, unitId, unit, syllabusId: getState().jobId }),
    );

    clear(list);
    unit.topics.forEach((t, i) => {
      const pending = t.status !== undefined && t.status !== "ready";
      // t.blocks holds this topic's actual subtopic rows once it's been
      // generated (populated in the store the first time this topic's
      // content is fetched - see learn.js/setTopicBlocks). deliberately
      // NOT fetching subtopics here for every topic on this screen: that
      // would force-generate every topic in the unit just to show a
      // preview, burning llm calls for topics nobody's opened yet. topics
      // that haven't been visited simply show no child nodes yet.
      const subtopics = Array.isArray(t.blocks) ? t.blocks : [];

      const item = el("li", { class: "nsya-rise", style: `animation-delay:${i * 70}ms` }, [
        el(
          "button",
          {
            type: "button",
            class: "pipeline__item",
            onclick: () => navigate(`/learn/${subject.id}/${unit.id}/${t.id}`),
          },
          [
            el("span", { class: `pipeline__node ${t.completed ? "is-complete" : ""}` }, [
              t.completed
                ? el("span", { html: Icon.check("", 16) })
                : pending
                  ? el("span", { html: Icon.loader2("", 16) })
                  : el("span", { class: "tabular-nums" }, String(i + 1)),
            ]),
            el("span", { class: `pipeline__label ${t.completed ? "is-complete" : ""}` }, [
              el("span", { class: "truncate" }, t.name),
              t.accuracy !== null
                ? el("span", { class: "pipeline__accuracy tabular-nums" }, `${t.accuracy}%`)
                : pending
                  ? el("span", { class: "pipeline__status" }, t.status)
                  : null,
            ]),
          ],
        ),
      ]);

      // topic = parent node; its subtopics render as a row of small child
      // dots underneath, each one labeled via title attribute (native
      // tooltip) with its actual subtopic name - a lightweight visual for
      // the real Topic -> Subtopic relationship without a full sub-screen
      if (subtopics.length > 0) {
        const children = el(
          "div",
          { class: "pipeline__subnodes" },
          subtopics.map((s) =>
            el("span", { class: "pipeline__subnode", title: s.title }),
          ),
        );
        item.appendChild(children);
      }

      list.appendChild(item);
    });

    if (unit.topics.length === 0) {
      list.appendChild(el("p", { class: "pipeline__empty" }, "This unit has no topics yet."));
    }
  }

  draw();
  const unsub = subscribe(draw);
  const stopSync = useJobSync();

  return () => {
    unsub();
    stopSync();
  };
}
