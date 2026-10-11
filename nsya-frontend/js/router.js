/**
 * Minimal hash router. Routes mirror the original TanStack Router paths
 * exactly, just prefixed with `#`:
 *
 *   #/                                        -> ingest
 *   #/uploading                                -> uploading
 *   #/extracting                               -> extracting
 *   #/graph                                    -> graph
 *   #/arc/:subjectId                           -> arc
 *   #/pipeline/:subjectId/:unitId              -> pipeline
 *   #/learn/:subjectId/:unitId/:topicId        -> learn
 *   #/profile                                  -> profile
 *
 * No server-side routing needed — open index.html directly or serve it
 * statically from anywhere.
 */

const routes = [];
let current = null; // { screen, cleanup }
let notFoundHandler = null;

export function registerRoute(pattern, handler) {
  const paramNames = [];
  const regex = new RegExp(
    "^" +
      pattern
        .split("/")
        .map((seg) => {
          if (seg.startsWith(":")) {
            paramNames.push(seg.slice(1));
            return "([^/]+)";
          }
          return seg.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        })
        .join("/") +
      "$",
  );
  routes.push({ regex, paramNames, handler });
}

export function setNotFound(handler) {
  notFoundHandler = handler;
}

export function navigate(path) {
  if (location.hash.slice(1) === path) {
    render();
  } else {
    location.hash = path;
  }
}

function parseHash() {
  let hash = location.hash.slice(1);
  if (!hash) hash = "/";
  const [pathPart] = hash.split("?");
  return pathPart;
}

async function render() {
  const path = parseHash();

  if (current?.cleanup) {
    try {
      current.cleanup();
    } catch {
      /* ignore */
    }
  }
  current = null;

  for (const route of routes) {
    const m = path.match(route.regex);
    if (m) {
      const params = {};
      route.paramNames.forEach((name, i) => (params[name] = decodeURIComponent(m[i + 1])));
      const cleanup = await route.handler(params);
      current = { cleanup: typeof cleanup === "function" ? cleanup : null };
      return;
    }
  }

  if (notFoundHandler) notFoundHandler();
}

export function startRouter() {
  window.addEventListener("hashchange", render);
  render();
}
