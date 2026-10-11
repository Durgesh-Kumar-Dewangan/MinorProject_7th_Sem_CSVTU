import { el } from "./utils.js";

/**
 * Renders the backend's explainability report (services/rag_pipeline.py) for
 * both places that show it: the per-lesson popup (games/theory-reader.js) and
 * the per-unit drawer (xai-panel.js). One renderer, so they can't drift apart.
 *
 *   Phase 4 - Explainable AI : retrieval trace (hybrid), context relevance,
 *             retrieval attribution, evidence tracing, SHAP (Shapley values)
 *   Phase 5 - Responsible AI : groundedness, faithfulness, hallucination
 *             risk, semantic similarity, evidence verification, trust score
 *   -> "Final trustworthy response": trust score + band
 *
 * Any metric the backend could not compute arrives as null and is drawn as
 * "N/A" - never as a made-up 0%.
 */

const BAND_TEXT = {
  high: "High trust",
  medium: "Medium trust - verify the key points",
  low: "Low trust - check against your own material",
};

const VERDICT_TEXT = { supported: "supported", weak: "weak", unsupported: "unsupported" };

function pct(v) {
  return Math.max(0, Math.min(100, Math.round(v * 100)));
}

export function scoreBar(label, value, { title, tone } = {}) {
  if (value === null || value === undefined) {
    return el("div", { class: "xai-score-row", title: title || "" }, [
      el("span", { class: "xai-score-row__label" }, label),
      el("span", { class: "xai-score-row__na" }, " N/A"),
    ]);
  }
  const p = pct(value);
  return el("div", { class: "xai-score-row", title: title || "" }, [
    el("div", { class: "xai-score-row__head" }, [
      el("span", { class: "xai-score-row__label" }, label),
      el("span", { class: "xai-score-row__value tabular-nums" }, `${p}%`),
    ]),
    el("div", { class: "xai-score-row__track" }, [
      el("div", { class: `xai-score-row__fill${tone ? ` is-${tone}` : ""}`, style: `width:${p}%` }),
    ]),
  ]);
}

function chip(text, cls = "") {
  return el("span", { class: `xai-chip ${cls}`.trim() }, text);
}

function group(title, hint, children, { open = false } = {}) {
  const d = el("details", { class: "xai-group", ...(open ? { open: true } : {}) }, [
    el("summary", { class: "xai-group__title" }, [title, hint ? el("span", { class: "xai-group__hint" }, ` ${hint}`) : null]),
    el("div", { class: "xai-group__body" }, children),
  ]);
  return d;
}

function trustSection(info) {
  const box = el("div", { class: "xai-trust" });
  if (info.trust_score === null || info.trust_score === undefined) {
    box.appendChild(el("p", { class: "xai-trust__na" }, info.validation_note
      ? `Trust score unavailable: ${info.validation_note}.`
      : "Trust score unavailable for this lesson."));
    return box;
  }
  box.appendChild(el("div", { class: "xai-trust__head" }, [
    el("span", { class: "xai-trust__label" }, "Trust score"),
    chip(BAND_TEXT[info.trust_band] || info.trust_band, `xai-chip--band-${info.trust_band}`),
  ]));
  box.appendChild(scoreBar("", info.trust_score, {
    tone: info.trust_band === "high" ? "good" : info.trust_band === "medium" ? "warn" : "bad",
    title: "Weighted composite of groundedness, faithfulness, low hallucination risk, semantic similarity and retrieval confidence.",
  }));
  if (info.similarity_method) {
    box.appendChild(el("p", { class: "xai-note" },
      info.similarity_method === "embedding"
        ? "Similarity measured with sentence embeddings."
        : "Similarity measured lexically (TF-IDF): the embedding model was not available."));
  }
  return box;
}

function validationSection(info) {
  return group("Responsible AI validation", "Phase 5", [
    scoreBar("Groundedness", info.groundedness, { title: "How close the lesson's sentences are to the retrieved evidence, on average." }),
    scoreBar("Faithfulness", info.faithfulness, { title: "Share of lesson sentences that have clearly supporting evidence." }),
    scoreBar("Hallucination risk", info.hallucination_risk, {
      tone: "risk",
      title: "Sentences with no supporting evidence (weakly supported ones count half). Lower is better. 'Unsupported' means not backed by your material, not necessarily false.",
    }),
    scoreBar("Semantic similarity", info.semantic_similarity, { title: "Whole lesson vs the whole retrieved context." }),
    scoreBar("Topic alignment", info.topic_alignment, { title: "Whole lesson vs the topic it should be about." }),
  ], { open: true });
}

function verificationSection(info) {
  const counts = info.verdict_counts || {};
  const kids = [
    el("div", { class: "xai-chips" }, ["supported", "weak", "unsupported"].map((k) =>
      chip(`${counts[k] || 0} ${VERDICT_TEXT[k]}`, `xai-chip--${k}`))),
  ];
  const flagged = info.flagged_sentences || [];
  if (flagged.length) {
    kids.push(el("p", { class: "xai-note" }, "Sentences to double-check:"));
    const ul = el("ul", { class: "xai-list" });
    flagged.forEach((f) => ul.appendChild(el("li", { class: "xai-list__item" }, [
      chip(f.verdict, `xai-chip--${f.verdict}`),
      el("span", { class: "xai-list__text" }, `"${f.sentence}"`),
      f.reasons?.length ? el("span", { class: "xai-list__reason" }, f.reasons.join("; ")) : null,
    ])));
    kids.push(ul);
  } else if ((counts.supported || 0) > 0) {
    kids.push(el("p", { class: "xai-note" }, "Every sentence is backed by the retrieved evidence."));
  }
  return group("Evidence verification", "Phase 5", kids);
}

function retrievalSection(info) {
  const r = info.retrieval || {};
  const kids = [];
  const methodText = {
    hybrid: "Hybrid: vector + keyword",
    "keyword-only": "Keyword only (no vector index or embedding model)",
    "vector-only": "Vector only",
    "excerpt-fallback": "No index yet - ranked the syllabus text directly",
    none: "No evidence retrieved",
  }[r.method] || r.method;
  kids.push(el("div", { class: "xai-chips" }, [
    chip(methodText),
    r.vector_used ? chip("vector search") : null,
    r.keyword_used ? chip("keyword (BM25)") : null,
    r.reranked ? chip("re-ranked") : null,
    r.selected ? chip(`${r.selected} of ${r.candidates || r.selected} candidates selected`) : null,
  ]));
  const rel = info.context_relevance || [];
  rel.forEach((c) => {
    kids.push(el("div", { class: "xai-evidence" }, [
      el("div", { class: "xai-evidence__head" }, [
        chip(c.modality || "text", `xai-chip--${c.modality || "text"}`),
        el("span", { class: "xai-evidence__source" }, c.source),
        el("span", { class: "xai-evidence__meta" },
          `rank ${c.rank}` + (c.sentences_supported ? ` · backs ${c.sentences_supported} sentence${c.sentences_supported === 1 ? "" : "s"}` : "")),
      ]),
      scoreBar("Context relevance", c.relevance),
      el("p", { class: "xai-evidence__snippet" }, `"${c.snippet}"`),
      (c.vector_score !== null && c.vector_score !== undefined) || c.keyword_score
        ? el("p", { class: "xai-note" }, [
          c.vector_score !== null && c.vector_score !== undefined ? `vector ${pct(c.vector_score)}%` : null,
          c.vector_score !== null && c.vector_score !== undefined && c.keyword_score ? " · " : null,
          c.keyword_score ? `keyword ${pct(c.keyword_score)}%` : null,
        ])
        : null,
    ]));
  });
  if (!rel.length) kids.push(el("p", { class: "xai-note" }, "No evidence chunks to show."));
  return group("Hybrid retrieval and context relevance", "Phase 4", kids);
}

function attributionSection(info) {
  const kids = [];
  if (info.attribution?.length) {
    kids.push(el("p", { class: "xai-note" }, "Retrieval attribution - share of grounding per source document:"));
    info.attribution.forEach((a) => kids.push(scoreBar(a.source, a.weight)));
  }
  const shap = info.shap;
  if (shap?.available && shap.values?.length) {
    kids.push(el("p", { class: "xai-note" },
      `SHAP (${shap.method === "shapley-exact" ? "exact Shapley values" : "sampled Shapley values"}) - how much each evidence chunk contributes to the lesson's groundedness:`));
    shap.values.forEach((v) => kids.push(scoreBar(`#${v.chunk_index + 1} ${v.source}`, Math.max(0, v.share),
      { title: `"${v.snippet}"` })));
  }
  if (!kids.length) kids.push(el("p", { class: "xai-note" }, "No attribution available (no retrieved evidence)."));
  return group("Attribution and SHAP", "Phase 4", kids);
}

function traceSection(info) {
  const trace = info.evidence_trace || [];
  if (!trace.length) return null;
  const ul = el("ul", { class: "xai-list" });
  trace.slice(0, 12).forEach((t) => ul.appendChild(el("li", { class: "xai-list__item" }, [
    chip(t.verdict, `xai-chip--${t.verdict}`),
    el("span", { class: "xai-list__text" }, `"${t.sentence}"`),
    el("span", { class: "xai-list__reason" }, `\u2192 ${t.modality || "text"} evidence from ${t.source} (${pct(t.similarity)}% similar)`),
  ])));
  return group("Evidence tracing", "Phase 4", [ul]);
}

/**
 * Why the lesson came from whoever it came from.
 *
 * Without this, a rejected API key, a retired model name and "no provider
 * configured at all" all looked identical from the outside: a template
 * lesson, with the panel cheerfully reporting "no LLM configured". The
 * backend now records one outcome per provider it tried, so a
 * misconfiguration is visible and fixable instead of looking like the
 * feature is broken.
 */
function providerSection(info) {
  const attempts = info.provider_attempts || [];
  if (!attempts.length) return null;

  const failures = attempts.filter((a) => a.outcome !== "ok");
  // Nothing to explain when the first provider tried just worked.
  if (!failures.length && info.generated_by !== "template") return null;

  const kids = [];
  if (info.generated_by === "template") {
    kids.push(
      el(
        "p",
        { class: "xai-note" },
        failures.length
          ? "This lesson used the built-in template because every configured provider failed:"
          : "This lesson used the built-in template - no provider is configured.",
      ),
    );
  } else {
    kids.push(el("p", { class: "xai-note" }, `Earlier providers were tried first and did not answer:`));
  }

  const ul = el("ul", { class: "xai-list" });
  attempts.forEach((a) =>
    ul.appendChild(
      el("li", { class: "xai-list__item" }, [
        chip(a.provider, a.outcome === "ok" ? "xai-chip--supported" : "xai-chip--unsupported"),
        el("span", { class: "xai-list__text" }, a.outcome),
      ]),
    ),
  );
  kids.push(ul);

  if (failures.some((f) => /API key/i.test(f.outcome))) {
    kids.push(el("p", { class: "xai-note" }, "Set the key in backend/.env, then restart the backend."));
  }
  if (failures.some((f) => /HTTP 4\d\d/.test(f.outcome))) {
    kids.push(
      el(
        "p",
        { class: "xai-note" },
        "A 4xx usually means the key was rejected or the model name is no longer available - check the message above against your provider's console.",
      ),
    );
  }

  return group("Which model wrote this", "Phase 3", kids, { open: info.generated_by === "template" });
}

function optimizationNote(info) {
  const o = info.optimization;
  if (!o?.regenerated) return null;
  const before = o.trust_before !== undefined ? `${pct(o.trust_before)}%` : "?";
  const after = o.trust_after !== undefined && o.trust_after !== null ? `${pct(o.trust_after)}%` : "?";
  return el("p", { class: "xai-note" },
    `Response optimization: the first draft scored low (${before}), so it was regenerated with stricter grounding (${after}); kept the ${o.kept === "strict-regeneration" ? "regenerated draft" : "first draft"}.`);
}

export function renderTrustReport(info) {
  const root = el("div", { class: "xai-report" });
  root.appendChild(trustSection(info));
  const provider = providerSection(info);
  if (provider) root.appendChild(provider);
  const opt = optimizationNote(info);
  if (opt) root.appendChild(opt);
  if (info.validation_available !== false) {
    root.appendChild(validationSection(info));
    root.appendChild(verificationSection(info));
  }
  root.appendChild(retrievalSection(info));
  root.appendChild(attributionSection(info));
  const trace = traceSection(info);
  if (trace) root.appendChild(trace);
  return root;
}
