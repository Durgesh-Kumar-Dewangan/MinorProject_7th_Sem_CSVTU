import { el } from "../utils.js";
import { Icon } from "../icons.js";
import { getTopicExplainability } from "../api.js";
import { renderTrustReport } from "../xai-metrics.js";

// theory reader - shows the lesson text broken into full subtopic blocks,
// plus a real web image if (and only if) one was actually found during
// generation. no loading spinner, no "no image found" placeholder - the
// image is resolved server-side as part of generation itself, so by the
// time this renders we already know for certain whether there's a real
// image or not. if there isn't, nothing image-related renders at all.
export function renderTheory(mount, blocks, topicId, image) {
  mount.innerHTML = "";

  if (!blocks || blocks.length === 0) {
    mount.appendChild(el("p", { class: "theory-empty" }, "Theory for this topic is still being generated."));
    return;
  }

  if (image?.url) {
    const link = el(
      "a",
      { href: image.source_url || image.url, target: "_blank", rel: "noopener noreferrer", class: "theory-image-area__link" },
      [el("img", { src: image.thumbnail_url || image.url, alt: image.title || "", class: "theory-image-area__img" })],
    );
    const area = el("div", { class: "theory-image-area" }, [link]);
    if (image.creator || image.license) {
      area.appendChild(
        el(
          "span",
          { class: "theory-image-area__attribution" },
          [image.creator ? `Image: ${image.creator}` : "Image", image.license ? ` · ${image.license}` : ""].join(""),
        ),
      );
    }
    mount.appendChild(area);
  }

  const list = el("div", { class: "theory-list" });
  mount.appendChild(list);

  // ---- small corner icon -> click opens a panel showing how this lesson
  // actually got made (which provider, whether RAG kicked in, which source
  // chunks it pulled from). purely informational, doesn't touch the lesson
  // itself, just tucked in the corner so it never gets in the way
  if (topicId) {
    renderExplainabilityCorner(mount, topicId);
  }

  function draw() {
    list.innerHTML = "";
    blocks.forEach((b, i) => {
      const article = el("article", { class: "theory-block nsya-rise", style: `animation-delay:${i * 60}ms` });
      article.appendChild(el("p", { class: "theory-block__eyebrow" }, `Subtopic ${i + 1}`));
      article.appendChild(el("h2", { class: "theory-block__title" }, b.title));

      const bodyWrap = el("div", { class: "theory-block__body" });
      b.body.split(/\n{2,}/).forEach((para) => bodyWrap.appendChild(el("p", {}, para)));
      article.appendChild(bodyWrap);

      if (b.source) {
        article.appendChild(
          el("p", { class: "theory-block__source" }, [
            el("span", { html: Icon.bookOpen("", 14) }),
            `Source: ${b.source}`,
          ]),
        );
      }

      list.appendChild(article);
    });
  }

  draw();
}

function renderExplainabilityCorner(mount, topicId) {
  const btn = el(
    "button",
    { type: "button", class: "xai-corner-btn", "aria-label": "How was this lesson made?" },
    [el("span", { html: Icon.helpCircle("", 16) })],
  );
  mount.appendChild(btn);

  let panel = null;
  let data = null;

  // "Final trustworthy response": show the trust score on the lesson itself,
  // not only inside the popup.
  getTopicExplainability(topicId)
    .then((d) => {
      data = d;
      if (d?.available && d.trust_score !== null && d.trust_score !== undefined) {
        btn.classList.add(`xai-corner-btn--${d.trust_band}`);
        btn.appendChild(el("span", { class: "xai-corner-btn__trust" }, `Trust ${Math.round(d.trust_score * 100)}%`));
        btn.setAttribute("aria-label", `How was this lesson made? Trust score ${Math.round(d.trust_score * 100)} percent`);
      }
    })
    .catch(() => {});

  function closePanel() {
    if (panel) {
      panel.remove();
      panel = null;
    }
    document.removeEventListener("click", onOutsideClick);
  }

  function onOutsideClick(e) {
    if (panel && !panel.contains(e.target) && e.target !== btn) closePanel();
  }

  async function openPanel() {
    if (panel) {
      closePanel();
      return;
    }
    panel = el("div", { class: "xai-panel" }, [
      el("p", { class: "xai-panel__loading" }, "Checking…"),
    ]);
    mount.appendChild(panel);
    setTimeout(() => document.addEventListener("click", onOutsideClick), 0);

    if (!data) {
      data = await getTopicExplainability(topicId).catch(() => ({ available: false }));
    }
    if (!panel) return; // closed while we were waiting

    panel.innerHTML = "";
    if (!data?.available) {
      panel.appendChild(el("p", { class: "xai-panel__row" }, "No details available for this lesson yet."));
      return;
    }

    const providerLabel = {
      ollama: "Ollama (local)",
      mistral: "Mistral",
      groq: "Groq",
      gemini: "Gemini",
      template: "Built-in template (no LLM configured)",
    }[data.generated_by] || data.generated_by;

    panel.appendChild(el("p", { class: "xai-panel__title" }, "How this lesson was made"));
    panel.appendChild(
      el("div", { class: "xai-panel__row" }, [el("strong", {}, "Generated by: "), providerLabel]),
    );
    panel.appendChild(
      el("div", { class: "xai-panel__row" }, [
        el("strong", {}, "Grounded in source material: "),
        data.retrieval_used ? "yes" : "no (used a plain excerpt of the syllabus text)",
      ]),
    );

    // Phase 4 (explainable AI) + Phase 5 (responsible AI validation) report:
    // trust score, groundedness, faithfulness, hallucination risk, semantic
    // similarity, evidence verification, hybrid retrieval, attribution, SHAP.
    panel.appendChild(renderTrustReport(data));

    if (data.prerequisite_title) {
      panel.appendChild(
        el("div", { class: "xai-panel__row" }, [el("strong", {}, "Prerequisite: "), data.prerequisite_title]),
      );
    }
  }

  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    openPanel();
  });
}
