import { el, shuffle } from "../utils.js";
import { Icon } from "../icons.js";
import { gameShell, primaryButton } from "./game-shell.js";

/**
 * Floating keyword arrange: tap the drifting keyword chips in the right
 * order to write out the definition of the term.
 */
export function renderArrange(mount, { items, seed, onRegenerate, regenerating, onDone }) {
  const rolled = shuffle(items, seed);
  let index = 0;
  let placed = [];
  let score = 0;
  let checked = null; // null | true | false

  const { section, body, footer } = gameShell({
    iconHtml: Icon.shuffle("", 18),
    title: "Arrange the definition",
    hint: "Tap the floating keywords in order to build the definition.",
    onRegenerate,
    regenerating,
  });
  mount.appendChild(section);

  function draw() {
    const item = rolled[index];
    if (!item) return;

    const chips = shuffle([...item.keywords, ...(item.distractors ?? [])], seed + index);
    const isRight = placed.length === item.keywords.length && placed.every((w, i) => w === item.keywords[i]);

    body.innerHTML = "";
    body.appendChild(
      el("p", { class: "game__eyebrow" }, `${index + 1} / ${rolled.length} · ${item.term}`),
    );

    const sentence = el("div", { class: "sentence-box" });
    if (placed.length) {
      const p = el("p", {});
      placed.forEach((w, i) => {
        p.appendChild(
          el(
            "button",
            {
              type: "button",
              class: "placed-chip",
              onclick: () => {
                if (checked !== null) return;
                placed = placed.filter((_, pi) => pi !== i);
                draw();
              },
            },
            w,
          ),
        );
      });
      sentence.appendChild(p);
    } else {
      sentence.appendChild(el("p", { class: "sentence-box__placeholder" }, "Your definition appears here…"));
    }
    body.appendChild(sentence);

    const bank = el("div", { class: "chip-bank" });
    chips
      .filter((c) => !placed.includes(c))
      .forEach((c, i) => {
        bank.appendChild(
          el(
            "button",
            {
              type: "button",
              class: "chip",
              disabled: checked !== null,
              style: `animation:nsya-float ${4 + (i % 4) * 0.6}s ease-in-out ${i * 0.18}s infinite`,
              onclick: () => {
                placed = [...placed, c];
                draw();
              },
            },
            c,
          ),
        );
      });
    body.appendChild(bank);

    if (checked !== null) {
      body.appendChild(
        el("div", { class: `result-note ${checked ? "" : "is-wrong"}` }, [
          checked ? "Correct arrangement." : "Not quite — the definition reads:",
          el("span", { class: "result-note__answer" }, item.definition ?? item.keywords.join(" ")),
        ]),
      );
    }

    footer.innerHTML = "";
    if (checked === null) {
      footer.appendChild(
        primaryButton(
          "Check definition",
          () => {
            checked = isRight;
            if (isRight) score += 1;
            draw();
          },
          placed.length === 0,
        ),
      );
    } else {
      footer.appendChild(
        primaryButton(index + 1 < rolled.length ? "Next term" : "Finish", () => {
          if (index + 1 < rolled.length) {
            index += 1;
            placed = [];
            checked = null;
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
