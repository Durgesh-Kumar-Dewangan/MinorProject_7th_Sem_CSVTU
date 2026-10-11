import { el, shuffle } from "../utils.js";
import { Icon } from "../icons.js";
import { gameShell, primaryButton } from "./game-shell.js";

/** Catch / pick up: tap only the drifting terms that truly belong to the topic. */
export function renderCatch(mount, { topic, items, seed, onRegenerate, regenerating, onDone }) {
  const rolled = shuffle(items, seed);
  let picked = [];
  let checked = false;

  const { section, body, footer } = gameShell({
    iconHtml: Icon.gamepad2("", 18),
    title: "Catch the concepts",
    hint: `Pick up only the terms that belong to ${topic}.`,
    onRegenerate,
    regenerating,
  });
  mount.appendChild(section);

  function draw() {
    const total = rolled.length || 1;
    const correct = rolled.filter((w) => w.ok === picked.includes(w.term)).length;

    body.innerHTML = "";
    const wrap = el("div", { class: "chip-bank centered" });
    rolled.forEach((w, i) => {
      const on = picked.includes(w.term);
      const tone = checked ? (w.ok === on ? "is-correct" : "is-wrong") : on ? "is-on" : "";
      wrap.appendChild(
        el(
          "button",
          {
            type: "button",
            class: `chip ${tone}`,
            disabled: checked,
            style: `animation:nsya-float ${4 + (i % 4) * 0.6}s ease-in-out ${i * 0.2}s infinite`,
            onclick: () => {
              picked = picked.includes(w.term) ? picked.filter((x) => x !== w.term) : [...picked, w.term];
              draw();
            },
          },
          w.term,
        ),
      );
    });
    body.appendChild(wrap);

    if (checked) {
      body.appendChild(el("p", { class: "center-text", style: "margin-top:1.25rem;font-size:12.5px;color:var(--muted-foreground)" }, `${correct}/${total} terms judged correctly.`));
    }

    footer.innerHTML = "";
    footer.appendChild(
      checked
        ? primaryButton("Continue", () => onDone(correct, total))
        : primaryButton("Submit picks", () => {
            checked = true;
            draw();
          }),
    );
  }

  draw();
}
