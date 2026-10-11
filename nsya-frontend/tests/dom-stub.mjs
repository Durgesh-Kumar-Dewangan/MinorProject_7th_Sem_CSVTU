/**
 * The smallest DOM that will run this app's modules under plain Node.
 *
 * Why this exists: the frontend had a crash (`seed` was passed to all four
 * exercise games but never declared) that every static check missed, because
 * it is perfectly valid syntax - it only throws when the code actually runs.
 * `node --check` cannot see it, and the project has no browser-test setup.
 * This stub is enough to execute the real modules, unmodified, so that class
 * of bug fails a test instead of reaching a learner.
 *
 * Deliberately NOT a browser: no layout, no CSS, no HTML parsing. It
 * implements only what these modules touch - element creation, the tree,
 * attributes/classes, listeners, and simple class/tag selectors.
 */

class ClassList {
  constructor(el) {
    this.el = el;
  }
  _list() {
    return (this.el.className || "").split(/\s+/).filter(Boolean);
  }
  _set(list) {
    this.el.className = [...new Set(list)].join(" ");
  }
  add(...names) {
    this._set([...this._list(), ...names]);
  }
  remove(...names) {
    this._set(this._list().filter((c) => !names.includes(c)));
  }
  contains(name) {
    return this._list().includes(name);
  }
  toggle(name, force) {
    const on = force === undefined ? !this.contains(name) : !!force;
    if (on) this.add(name);
    else this.remove(name);
    return on;
  }
}

class Node {
  constructor(tag) {
    this.tagName = String(tag || "").toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.attributes = {};
    this.className = "";
    this.style = {};
    this.listeners = {};
    this.classList = new ClassList(this);
    this._text = "";
    this._html = "";
    this.disabled = false;
    this.files = [];
  }

  get firstChild() {
    return this.children[0] ?? null;
  }

  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    return child;
  }
  removeChild(child) {
    this.children = this.children.filter((c) => c !== child);
    child.parentNode = null;
    return child;
  }
  remove() {
    this.parentNode?.removeChild(this);
  }
  contains(other) {
    if (other === this) return true;
    return this.children.some((c) => (c.contains ? c.contains(other) : false));
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
    if (name === "class") this.className = String(value);
    if (name === "disabled") this.disabled = true;
  }
  getAttribute(name) {
    return this.attributes[name] ?? null;
  }
  removeAttribute(name) {
    delete this.attributes[name];
  }

  addEventListener(type, fn) {
    (this.listeners[type] ||= []).push(fn);
  }
  removeEventListener(type, fn) {
    this.listeners[type] = (this.listeners[type] || []).filter((f) => f !== fn);
  }
  dispatch(type, event = {}) {
    const ev = { type, target: this, preventDefault() {}, stopPropagation() {}, ...event };
    for (const fn of [...(this.listeners[type] || [])]) fn(ev);
  }

  // `html:` in utils.el sets innerHTML with an inline SVG string. Nothing in
  // the app reads it back or queries into it, so it is stored as opaque text
  // rather than parsed - and assigning "" is the app's "clear this node"
  // idiom, which must really empty the subtree.
  set innerHTML(v) {
    this._html = String(v);
    if (v === "") this.children = [];
  }
  get innerHTML() {
    return this._html;
  }

  set textContent(v) {
    this._text = String(v);
    this.children = [];
  }
  get textContent() {
    if (this.children.length === 0) return this._text;
    return this.children.map((c) => c.textContent).join("");
  }

  _matches(selector) {
    if (selector.startsWith(".")) return this.classList.contains(selector.slice(1));
    return this.tagName === selector.toUpperCase();
  }
  _walk(out) {
    for (const c of this.children) {
      if (c instanceof Node) {
        out.push(c);
        c._walk(out);
      }
    }
    return out;
  }
  querySelectorAll(selector) {
    // One simple selector only (".cls" or "tag") - all this app uses.
    return this._walk([]).filter((n) => n._matches(selector));
  }
  querySelector(selector) {
    return this.querySelectorAll(selector)[0] ?? null;
  }
}

class TextNode {
  constructor(text) {
    this._text = String(text);
    this.children = [];
  }
  get textContent() {
    return this._text;
  }
  _matches() {
    return false;
  }
  _walk(out) {
    return out;
  }
  contains(other) {
    return other === this;
  }
}

function makeStorage() {
  const map = new Map();
  return {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)),
    removeItem: (k) => map.delete(k),
    clear: () => map.clear(),
  };
}

/** Installs the stub onto globalThis. Call once, before importing app modules. */
export function installDom({ apiBase = "http://127.0.0.1:8000" } = {}) {
  const document = {
    title: "",
    createElement: (tag) => new Node(tag),
    createElementNS: (_ns, tag) => new Node(tag),
    createTextNode: (text) => new TextNode(text),
    addEventListener() {},
    removeEventListener() {},
    body: new Node("body"),
    _nodesById: {},
    getElementById(id) {
      return this._nodesById[id] ?? null;
    },
  };
  document._nodesById.app = new Node("div");
  document._nodesById["toast-root"] = new Node("div");

  const window = {
    NSYA_API_URL: apiBase,
    innerWidth: 1280,
    innerHeight: 900,
    addEventListener() {},
    removeEventListener() {},
    location: { hash: "" },
    localStorage: makeStorage(),
  };

  globalThis.document = document;
  globalThis.window = window;
  globalThis.location = window.location;
  globalThis.localStorage = window.localStorage;
  globalThis.Node = Node;

  return { document, window, root: document._nodesById.app };
}

/* ----------------------------- test helpers ----------------------------- */

/** Every element in the tree, depth-first. */
export function allNodes(root) {
  return root._walk([]);
}

/** Find an element whose visible text contains `text` (buttons by default). */
export function findByText(root, text, { tag = "BUTTON" } = {}) {
  const want = text.toLowerCase();
  return (
    allNodes(root).find(
      (n) => n.tagName === tag && (n.textContent || "").toLowerCase().includes(want),
    ) ?? null
  );
}

export function click(node) {
  if (!node) throw new Error("click() got null - the element was not found");
  if (node.disabled) throw new Error(`refusing to click a disabled element: "${node.textContent}"`);
  node.dispatch("click");
}

/** Visible text of the whole tree, whitespace-collapsed. */
export function textOf(root) {
  return (root.textContent || "").replace(/\s+/g, " ").trim();
}
