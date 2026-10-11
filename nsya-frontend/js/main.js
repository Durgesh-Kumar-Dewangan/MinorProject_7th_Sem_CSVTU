import { registerRoute, setNotFound, startRouter, navigate } from "./router.js";
import { renderIngest } from "./screens/ingest.js";
import { renderUploading } from "./screens/uploading.js";
import { renderExtracting } from "./screens/extracting.js";
import { renderGraph } from "./screens/graph.js";
import { renderArc } from "./screens/arc.js";
import { renderPipeline } from "./screens/pipeline.js";
import { renderProfile } from "./screens/profile.js";
import { renderLearn } from "./screens/learn.js";

const root = document.getElementById("app");

registerRoute("/", () => renderIngest(root));
registerRoute("/uploading", () => renderUploading(root));
registerRoute("/extracting", () => renderExtracting(root));
registerRoute("/graph", () => renderGraph(root));
registerRoute("/arc/:subjectId", (params) => renderArc(root, params));
registerRoute("/pipeline/:subjectId/:unitId", (params) => renderPipeline(root, params));
registerRoute("/learn/:subjectId/:unitId/:topicId", (params) => renderLearn(root, params));
registerRoute("/profile", () => renderProfile(root));

setNotFound(() => navigate("/"));

startRouter();
