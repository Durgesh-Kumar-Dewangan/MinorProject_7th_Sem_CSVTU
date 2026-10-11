import { el } from "./utils.js";
import { Icon } from "./icons.js";
import { navigate } from "./router.js";

const RAIL_ITEMS = [
  { key: "upload", icon: "upload", label: "Upload", go: () => navigate("/") },
  { key: "subjects", icon: "boxes", label: "Subjects", go: () => navigate("/graph") },
  {
    key: "units",
    icon: "layers",
    label: "Units",
    go: (ctx) => navigate(ctx.subjectId ? `/arc/${ctx.subjectId}` : "/graph"),
  },
  {
    key: "topics",
    icon: "listTree",
    label: "Topics",
    go: (ctx) =>
      navigate(ctx.subjectId && ctx.unitId ? `/pipeline/${ctx.subjectId}/${ctx.unitId}` : "/graph"),
  },
  { key: "profile", icon: "user", label: "Profile", go: () => navigate("/profile") },
];

function wordmark() {
  const a = el(
    "a",
    { class: "wordmark", href: "#/", onclick: (e) => (e.preventDefault(), navigate("/")) },
    ["NSYA", el("span", {}, ".AI")],
  );
  return a;
}

function sideRail({ active, subjectId, unitId } = {}) {
  const inner = el("div", { class: "rail__inner" });
  for (const item of RAIL_ITEMS) {
    const enabled = item.key === "units" ? Boolean(subjectId) : item.key === "topics" ? Boolean(subjectId && unitId) : true;
    const btn = el(
      "button",
      {
        type: "button",
        class: "rail__btn",
        title: item.label,
        "aria-label": item.label,
        "aria-current": active === item.key ? "page" : null,
        disabled: !enabled,
        onclick: () => enabled && item.go({ subjectId, unitId }),
      },
      [el("span", { html: Icon[item.icon]("", 18) }), el("span", { class: "rail__tip" }, item.label)],
    );
    inner.appendChild(btn);
  }
  return el("nav", { "aria-label": "Sections", class: "rail" }, inner);
}

export function backButton(label, onClick) {
  return el("button", { type: "button", class: "back-btn", onclick: onClick }, [
    el("span", { "aria-hidden": "true" }, "←"),
    " " + label,
  ]);
}

const WIDTHS = { sm: "page--sm", md: "page--md", lg: "page--lg", xl: "page--xl" };

/**
 * Renders the shared shell into #app and returns the `.page` content
 * container to append screen-specific markup into.
 *
 * opts: { active, subjectId, unitId, title, subtitle, back, center, width }
 */
export function renderShell(root, opts = {}) {
  const { active, subjectId, unitId, title, subtitle, back, center = false, width = "md" } = opts;

  const main = el("main", { class: "screen" });
  main.appendChild(wordmark());
  main.appendChild(sideRail({ active, subjectId, unitId }));
  if (back) main.appendChild(back);

  const page = el("div", {
    class: ["page", center ? "page--center" : "", WIDTHS[width] || WIDTHS.md].filter(Boolean).join(" "),
  });

  if (title) {
    const header = el("header", { class: "page__header" }, [
      el("h1", { class: "page__title" }, title),
      subtitle ? el("p", { class: "page__subtitle" }, subtitle) : null,
    ]);
    page.appendChild(header);
  }

  main.appendChild(page);

  root.innerHTML = "";
  root.appendChild(main);
  return page;
}
