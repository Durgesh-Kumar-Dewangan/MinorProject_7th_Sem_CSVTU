import { el, shuffle } from "../utils.js";
import { Icon } from "../icons.js";
import { gameShell, primaryButton } from "./game-shell.js";

/** Multiple-choice quiz. Options are re-shuffled on every regeneration. */
export function renderQuiz(mount, { questions, seed, onRegenerate, regenerating, onDone }) {
  const rolled = shuffle(questions, seed).map((q, qi) => {
    const opts = shuffle(
      q.options.map((label, i) => ({ label, correct: i === q.answer })),
      seed + qi / 10,
    );
    return { q: q.q, opts };
  });

  const answers = [];

  const { section, body, footer } = gameShell({
    iconHtml: Icon.helpCircle("", 18),
    title: "Quiz",
    hint: "Pick the correct answer for each question.",
    onRegenerate,
    regenerating,
  });

  const submitBtn = primaryButton("Submit answers", () => {
    const correct = rolled.filter((r, i) => r.opts[answers[i]]?.correct).length;
    onDone(correct, rolled.length);
  }, true);
  footer.appendChild(submitBtn);

  const list = el("div", { class: "quiz-list" });
  rolled.forEach((r, qi) => {
    const optsWrap = el("div", { class: "quiz-opts" });
    r.opts.forEach((o, oi) => {
      const btn = el(
        "button",
        {
          type: "button",
          class: "quiz-opt",
          onclick: () => {
            answers[qi] = oi;
            optsWrap.querySelectorAll(".quiz-opt").forEach((n, ni) => n.classList.toggle("is-picked", ni === oi));
            submitBtn.disabled = answers.filter((a) => a !== undefined).length < rolled.length;
          },
        },
        [el("span", { class: "quiz-opt__letter" }, String.fromCharCode(65 + oi)), el("span", {}, o.label)],
      );
      optsWrap.appendChild(btn);
    });
    list.appendChild(el("div", { class: "quiz-q" }, [el("p", { class: "quiz-q__text" }, r.q), optsWrap]));
  });
  body.appendChild(list);

  mount.appendChild(section);
}
