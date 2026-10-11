import { renderShell, backButton } from "../shell.js";
import { Icon } from "../icons.js";
import { el } from "../utils.js";
import { getTopicContent, postTopicResult } from "../api.js";
import { useJobSync } from "../job-sync.js";
import { completeTopic, findSubject, findTopic, findUnit, setTopicBlocks, getState, setTopicStage, getTopicStage, clearTopicStage } from "../store.js";
import { navigate } from "../router.js";

import { renderTheory } from "../games/theory-reader.js";
import { primaryButton } from "../games/game-shell.js";
import { renderQuiz } from "../games/quiz.js";
import { renderArrange } from "../games/arrange.js";
import { renderFill } from "../games/fill.js";
import { renderCatch } from "../games/catch.js";

export function renderLearn(root, { subjectId, unitId, topicId }) {
  if (getState().subjects.length === 0) {
    navigate("/");
    return;
  }

  const subject = findSubject(getState().subjects, subjectId);
  const unit = findUnit(subject, unitId);
  const topic = findTopic(unit, topicId);
  if (!subject || !unit || !topic) {
    navigate("/graph");
    return;
  }

  // resume wherever the learner left off on this topic instead of always
  // restarting at theory - this is the actual fix for "continue takes me
  // back to the start": stage was never persisted anywhere before, so
  // leaving mid-topic and coming back always reset to the very beginning.
  // still starts at "loading" if there's nothing to resume, or if content
  // hasn't loaded yet - see load() below for how that transitions.
  let stage = "loading";
  let resumeStage = getTopicStage(topicId); // read once at mount; consumed by load() below once content is ready
  let content = null;
  let error = null;
  let regenerating = false;
  let scores = {};
  let alive = true;
  let pollTimer = null;

  // Shuffle seed for the four exercise games (quiz/arrange/fill/catch). Every
  // game derives its chip/option order from this via utils.shuffle, so one
  // seed per round keeps an exercise stable while the learner works through
  // it (re-draws on every click must not re-shuffle under their fingers),
  // and re-rolling it in regenerate() gives a genuinely different layout for
  // the next round. Must stay declared here: the games take it as a required
  // option, and a missing binding throws before any game renders.
  let seed = Math.random();

  const stopSync = useJobSync();

  async function load(isRegenerate = false) {
    error = null;
    try {
      const c = await getTopicContent(topicId, { regenerate: isRegenerate });
      if (!alive) return;
      content = c;
      if (c.blocks?.length) setTopicBlocks(topicId, c.blocks);
      if (stage === "loading") {
        // only consume resumeStage once, right when content first becomes
        // available - and only if it's still a valid stage for THIS
        // generation (e.g. don't resume into "quiz" if this content
        // somehow has no quiz items)
        const validStages = stagesFor();
        stage = resumeStage && validStages.includes(resumeStage) ? resumeStage : "theory";
        resumeStage = null;
      }
      draw();
    } catch (e) {
      if (!alive) return;
      error = e instanceof Error ? e.message : "Could not load this topic";
      if (stage === "loading") stage = "theory";
      draw();
    }
  }

  function schedulePoll() {
    clearTimeout(pollTimer);
    if (!content || content.status === "ready" || content.status === undefined) return;
    pollTimer = setTimeout(async () => {
      await load(false);
      schedulePoll();
      draw();
    }, 2500);
  }

  async function regenerate() {
    regenerating = true;
    seed = Math.random(); // fresh exercise order to go with the freshly generated content
    draw();
    await load(true); // true = force genuinely fresh content, bypassing the backend cache
    regenerating = false;
    schedulePoll();
    draw();
  }

  function backToPipeline() {
    navigate(`/pipeline/${subject.id}/${unit.id}`);
  }

  function stagesFor() {
    const quiz = content?.quiz ?? [];
    const arrange = content?.arrange ?? [];
    const fill = content?.fill ?? [];
    const catches = content?.catch ?? content?.recall ?? [];
    return [
      "theory",
      ...(quiz.length ? ["quiz"] : []),
      ...(arrange.length ? ["arrange"] : []),
      ...(fill.length ? ["fill"] : []),
      ...(catches.length ? ["catch"] : []),
      "score",
      "notes",
    ];
  }

  function record(key, correct, total) {
    scores = { ...scores, [key]: { correct, total } };
  }

  function accuracy() {
    const tallies = Object.values(scores);
    const totalCorrect = tallies.reduce((a, t) => a + t.correct, 0);
    const totalMax = tallies.reduce((a, t) => a + t.total, 0);
    return totalMax ? Math.round((totalCorrect / totalMax) * 100) : 0;
  }

  function draw() {
    if (!alive) return;

    if (stage === "loading") {
      // just a plain spinner while we wait on the backend, no game here anymore
      root.innerHTML = "";
      root.appendChild(
        el("main", { class: "screen loading-screen" }, [
          el("div", { class: "loading-screen__inner" }, [
            el("span", { class: "loading-screen__spinner", html: Icon.refreshCw("nsya-spin", 22) }),
            el("p", { class: "loading-screen__text" }, "Loading your lesson..."),
          ]),
        ]),
      );
      return;
    }

    document.title = "Lesson canvas — NSYA.AI";

    // remember this as the resume point for next time this topic is opened
    setTopicStage(topicId, stage);

    const stages = stagesFor();
    const stageIndex = stages.indexOf(stage);
    const prevStage = stageIndex > 0 ? stages[stageIndex - 1] : undefined;

    const page = renderShell(root, {
      subjectId: subject.id,
      unitId: unit.id,
      active: "topics",
      width: "md",
      back: backButton(prevStage ? "Back" : "Topics", () => {
        if (prevStage) {
          stage = prevStage;
          draw();
        } else {
          backToPipeline();
        }
      }),
    });

    // topic header
    page.appendChild(
      el("div", { class: "learn__topic" }, [
        el("span", { class: "learn__topic-icon", html: Icon.sparkles("", 16) }),
        el("span", { class: "learn__topic-name truncate" }, topic.name),
      ]),
    );

    // stage rail
    const rail = el("div", { class: "stage-rail" });
    stages.forEach((s) => {
      rail.appendChild(
        el(
          "button",
          {
            type: "button",
            class: `stage-pill ${s === stage ? "is-active" : ""}`,
            onclick: () => {
              stage = s;
              draw();
            },
          },
          s,
        ),
      );
    });
    page.appendChild(rail);

    const blocks = content?.blocks?.length ? content.blocks : topic.blocks;
    const quiz = content?.quiz ?? [];
    const arrange = content?.arrange ?? [];
    const fill = content?.fill ?? [];
    const catches = content?.catch ?? content?.recall ?? [];
    const generating = content?.status === "generating" || content?.status === "pending";

    if (generating) {
      page.appendChild(
        el("p", { class: "generating-banner" }, [
          el("span", { html: Icon.refreshCw("nsya-spin", 14) }),
          "Content is still generating — this page updates live.",
        ]),
      );
    }

    if (error) {
      page.appendChild(
        el("div", { class: "error-panel" }, [
          el("span", { html: Icon.alertCircle("", 24) }),
          el("p", {}, error),
          el("p", {}, ["Lesson content comes from your backend endpoint ", el("code", {}, `GET /topics/${topicId}`)]),
        ]),
      );
    }

    if (stage === "theory" && !error) {
      const section = el("section", { style: "display:flex;flex-direction:column;gap:1.25rem" });
      const theoryMount = el("div", { class: "theory-mount" });
      renderTheory(theoryMount, blocks, topic.id, content?.image);
      section.appendChild(theoryMount);
      section.appendChild(
        primaryButton(stages[1] === "score" ? "See your score" : "Continue", () => {
          stage = stages[stageIndex + 1] ?? "score";
          draw();
        }),
      );
      page.appendChild(section);
    }

    if (stage === "quiz") {
      renderQuiz(page, {
        questions: quiz,
        seed,
        onRegenerate: regenerate,
        regenerating,
        onDone: (c, t) => {
          record("quiz", c, t);
          stage = stages[stages.indexOf("quiz") + 1] ?? "score";
          draw();
        },
      });
    }

    if (stage === "arrange") {
      renderArrange(page, {
        items: arrange,
        seed,
        onRegenerate: regenerate,
        regenerating,
        onDone: (c, t) => {
          record("arrange", c, t);
          stage = stages[stages.indexOf("arrange") + 1] ?? "score";
          draw();
        },
      });
    }

    if (stage === "fill") {
      renderFill(page, {
        items: fill,
        seed,
        onRegenerate: regenerate,
        regenerating,
        onDone: (c, t) => {
          record("fill", c, t);
          stage = stages[stages.indexOf("fill") + 1] ?? "score";
          draw();
        },
      });
    }

    if (stage === "catch") {
      renderCatch(page, {
        topic: topic.name,
        items: catches,
        seed,
        onRegenerate: regenerate,
        regenerating,
        onDone: (c, t) => {
          record("catch", c, t);
          stage = stages[stages.indexOf("catch") + 1] ?? "score";
          draw();
        },
      });
    }

    if (stage === "score") {
      const acc = accuracy();
      const list = el("ul", { class: "score-list" });
      Object.entries(scores).forEach(([k, v]) => {
        list.appendChild(
          el("li", {}, [el("span", {}, k), el("span", { class: "tabular-nums" }, `${v.correct}/${v.total}`)]),
        );
      });

      page.appendChild(
        el("section", { class: "center-text" }, [
          el("div", { class: "score-ring" }, [
            el("div", {}, [
              el("p", { class: "score-ring__pct tabular-nums" }, `${acc}%`),
              el("p", { class: "score-ring__label" }, "accuracy"),
            ]),
          ]),
          list,
          el("div", { class: "score-actions" }, [
            el(
              "button",
              {
                type: "button",
                class: "btn-secondary",
                onclick: () => {
                  scores = {};
                  regenerate();
                  stage = stages[1] ?? "theory";
                  draw();
                },
              },
              [el("span", { html: Icon.refreshCw("", 14) }), "New round"],
            ),
            el(
              "button",
              {
                type: "button",
                class: "btn-primary-inline",
                onclick: () => {
                  stage = "notes";
                  draw();
                },
              },
              "Read the topic notes",
            ),
          ]),
        ]),
      );
    }

    if (stage === "notes") {
      const panel = el("div", { class: "notes-panel nsya-scroll" });
      blocks.forEach((b, i) => {
        panel.appendChild(
          el("div", {}, [
            el("p", { class: "eyebrow" }, `${i + 1}. ${b.title}`),
            el("p", { class: "body" }, b.body),
            b.source ? el("p", { class: "src" }, `Source: ${b.source}`) : null,
          ]),
        );
      });
      if (content?.notes?.length) {
        const notesList = el("ul", { class: "notes-extra" });
        content.notes.forEach((line) => notesList.appendChild(el("li", {}, line)));
        panel.appendChild(notesList);
      }

      page.appendChild(el("h2", { class: "notes-title" }, `Structured notes · ${topic.name}`));
      page.appendChild(panel);
      page.appendChild(
        el(
          "button",
          {
            type: "button",
            class: "notes-complete",
            onclick: () => {
              const acc = accuracy();
              completeTopic(topic.id, acc);
              postTopicResult(topic.id, acc);
              clearTopicStage(topic.id); // completed - next visit starts fresh at theory, not stuck resuming at the score screen
              backToPipeline();
            },
          },
          [el("span", { html: Icon.check("", 16) }), "Mark topic complete & return"],
        ),
      );
    }
  }

  load(false).then(() => {
    schedulePoll();
    draw();
  });

  draw();

  return () => {
    alive = false;
    clearTimeout(pollTimer);
    stopSync();
  };
}
