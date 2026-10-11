/** el(tag, attrs, children) — tiny helper to build DOM without a framework. */
export function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") node.className = v;
    else if (k === "html") node.innerHTML = v;
    else if (k.startsWith("on") && typeof v === "function") {
      node.addEventListener(k.slice(2).toLowerCase(), v);
    } else if (v === false || v === null || v === undefined) {
      /* skip */
    } else if (v === true) {
      node.setAttribute(k, "");
    } else {
      node.setAttribute(k, v);
    }
  }
  const kids = Array.isArray(children) ? children : [children];
  for (const c of kids) {
    if (c === null || c === undefined || c === false) continue;
    node.appendChild(typeof c === "string" || typeof c === "number" ? document.createTextNode(String(c)) : c);
  }
  return node;
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

export function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

/** Deterministic-enough shuffle for client-side re-rolls (same as GameShell.shuffle). */
export function shuffle(items, seed = Math.random()) {
  const out = [...items];
  let s = Math.floor(seed * 100000) + 1;
  const rnd = () => {
    s = (s * 9301 + 49297) % 233280;
    return s / 233280;
  };
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(rnd() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

let toastRoot = null;
export function toast(message, { error = false, duration = 3200 } = {}) {
  if (!toastRoot) {
    toastRoot = document.getElementById("toast-root");
  }
  if (!toastRoot) return;
  const node = el("div", { class: `toast${error ? " is-error" : ""}` }, message);
  toastRoot.appendChild(node);
  setTimeout(() => node.remove(), duration);
}
