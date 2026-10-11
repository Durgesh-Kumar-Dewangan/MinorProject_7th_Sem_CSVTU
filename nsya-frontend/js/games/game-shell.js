import { el } from "../utils.js";
import { Icon } from "../icons.js";

/**
 * Shared chrome for every learning game: title, hint, a regenerate action
 * (re-rolls the exercise from the backend database) and a footer slot.
 * Returns { section, body, footer } so callers can fill body/footer.
 */
export function gameShell({ iconHtml, title, hint, onRegenerate, regenerating }) {
  const body = el("div", { class: "game__body" });
  const footer = el("div", { class: "game__footer" });

  const head = el("div", { class: "game__head" }, [
    el("span", { class: "game__icon", html: iconHtml }),
    el("div", { class: "game__title-wrap" }, [
      el("h2", { class: "game__title" }, title),
      hint ? el("p", { class: "game__hint" }, hint) : null,
    ]),
  ]);

  if (onRegenerate) {
    const btn = el(
      "button",
      {
        type: "button",
        class: "game__regen",
        title: "Generate a different exercise",
        disabled: !!regenerating,
        onclick: onRegenerate,
      },
      [el("span", { html: Icon.refreshCw(regenerating ? "nsya-spin" : "", 14) }), "New"],
    );
    head.appendChild(btn);
  }

  const section = el("section", { class: "game" }, [head, body, footer]);
  return { section, body, footer };
}

export function primaryButton(label, onClick, disabled = false) {
  return el("button", { type: "button", class: "btn-primary", disabled, onclick: onClick }, label);
}
