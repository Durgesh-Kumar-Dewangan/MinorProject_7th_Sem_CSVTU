import { el, shuffle } from "../utils.js";
import { Icon } from "../icons.js";
import { gameShell, primaryButton } from "./game-shell.js";

/**
 * Fill in the blank keyword to complete the definition. Every `___` in
 * `text` is one blank, filled from the keyword bank.
 */
export function renderFill(mount, { items, seed, onRegenerate, regenerating, onDone }) {
  const rolled = shuffle(items, seed);
  let index = 0;
  let filled = [];
  let checked = false;
  let score = 0;

  const { section, body, footer } = gameShell({
    iconHtml: Icon.penLine("", 18),
    title: "Complete the definition",
    hint: "Pick the keyword that fills each blank.",
    onRegenerate,
    regenerating,
  });
  mount.appendChild(section);

  function resetForItem() {
    const item = rolled[index];
    filled = item ? item.answers.map(() => null) : [];
    checked = false;
  }
  resetForItem();

  function draw() {
    const item = rolled[index];
    if (!item) return;

    const bank = shuffle(item.bank, seed + index);
    const parts = item.text.split("___");
    const complete = filled.every((f) => f !== null);
    const rightCount = filled.filter((f, i) => f === item.answers[i]).length;

    body.innerHTML = "";
    body.appendChild(el("p", { class: "game__eyebrow" }, `${index + 1} / ${rolled.length}`));

    const sentence = el("p", { class: "fill-sentence" });
    parts.forEach((part, i) => {
      sentence.appendChild(document.createTextNode(part));
      if (i < filled.length) {
        const isCorrect = checked && filled[i] === item.answers[i];
        const isWrong = checked && filled[i] !== item.answers[i];
        sentence.appendChild(
          el(
            "button",
            {
              type: "button",
              class: `fill-blank ${filled[i] ? "is-filled" : ""} ${isCorrect ? "is-correct" : ""} ${
                isWrong ? "is-wrong" : ""
              }`,
              onclick: () => {
                if (checked) return;
                filled = filled.map((x, xi) => (xi === i ? null : x));
                draw();
              },
            },
            filled[i] ?? "______",
          ),
        );
      }
    });
    body.appendChild(sentence);

    const bankWrap = el("div", { class: "chip-bank" });
    bank
      .filter((w) => !filled.includes(w))
      .forEach((w) => {
        bankWrap.appendChild(
          el(
            "button",
            {
              type: "button",
              class: "chip",
              disabled: checked,
              onclick: () => {
                const at = filled.findIndex((x) => x === null);
                if (at === -1) return;
                filled = [...filled];
                filled[at] = w;
                draw();
              },
            },
            w,
          ),
        );
      });
    body.appendChild(bankWrap);

    if (checked) {
      body.appendChild(
        el(
          "p",
          { class: "result-note" },
          `${rightCount}/${item.answers.length} blanks correct · answer: ${item.answers.join(", ")}`,
        ),
      );
    }

    footer.innerHTML = "";
    if (!checked) {
      footer.appendChild(
        primaryButton(
          "Check answer",
          () => {
            checked = true;
            score += rightCount === item.answers.length ? 1 : 0;
            draw();
          },
          !complete,
        ),
      );
    } else {
      footer.appendChild(
        primaryButton(index + 1 < rolled.length ? "Next definition" : "Finish", () => {
          if (index + 1 < rolled.length) {
            index += 1;
            resetForItem();
            draw();
          } else {
            onDone(score, rolled.length);
          }
        }),
      );
    }
  }

  draw();
}
