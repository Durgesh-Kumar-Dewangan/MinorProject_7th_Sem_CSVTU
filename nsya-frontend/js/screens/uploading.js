import { renderShell, backButton } from "../shell.js";
import { Icon } from "../icons.js";
import { el } from "../utils.js";
import { uploadSyllabus } from "../api.js";
import { getPendingFile, setJobId, getState } from "../store.js";
import { navigate } from "../router.js";

export function renderUploading(root) {
  document.title = "Uploading syllabus — NSYA.AI";

  const { fileName, fileSize } = getState();
  if (!fileName) {
    navigate("/");
    return;
  }

  let pct = 0;
  let status = "idle"; // idle | uploading | done | error
  let error = null;
  let abort = null;

  const page = renderShell(root, {
    active: "upload",
    center: true,
    width: "lg",
    title: "Send it to your backend",
    subtitle: "Upload the syllabus — progress updates live while the file transfers.",
    back: backButton("Ingest", () => navigate("/")),
  });

  // ring
  const ringCenter = el("div", { class: "upload-ring__center" });
  const ring = el("div", { class: "upload-ring" }, [
    el("div", { class: "upload-ring__track" }),
    el("div", { class: "upload-ring__fill" }),
    ringCenter,
  ]);
  const ringFill = ring.querySelector(".upload-ring__fill");

  // card
  const nameEl = el("p", { class: "upload-card__name truncate" }, fileName || "No file selected");
  const metaEl = el("p", { class: "upload-card__meta" });
  const barEl = el("div", { class: "upload-card__bar" });
  const errorSlot = el("div", {});
  const submitBtn = el("button", { type: "button", class: "btn-primary upload-card__submit" }, "Upload & extract");

  const card = el("div", { class: "upload-card" }, [
    el("div", { class: "upload-card__row" }, [
      el("div", { class: "" }, [nameEl, metaEl]),
      el(
        "button",
        { type: "button", class: "btn-pill", onclick: () => navigate("/") },
        "Change",
      ),
    ]),
    el("div", { class: "upload-card__track" }, barEl),
    errorSlot,
    submitBtn,
  ]);

  const grid = el("div", { class: "upload-grid" }, [ring, card]);
  page.appendChild(grid);

  function renderState() {
    const done = status === "done";
    const angle = (pct / 100) * 360;
    ringFill.style.background = `conic-gradient(var(--foreground) ${angle}deg, transparent 0deg)`;

    ringCenter.innerHTML = "";
    ringCenter.appendChild(
      done
        ? el("span", { html: Icon.check("", 28) })
        : status === "error"
          ? el("span", { class: "destructive", html: Icon.alertCircle("", 28) })
          : el("span", { class: "muted", html: Icon.fileUp("", 24) }),
    );
    ringCenter.appendChild(el("div", { class: "upload-ring__pct tabular-nums" }, `${pct}%`));

    metaEl.textContent = `${(fileSize / 1024).toFixed(0)} KB · ${
      done ? "Uploaded" : status === "uploading" ? "Uploading…" : status === "error" ? "Failed" : "Ready to upload"
    }`;
    barEl.style.width = `${pct}%`;

    errorSlot.innerHTML = "";
    if (error) errorSlot.appendChild(el("p", { class: "upload-card__error" }, error));

    submitBtn.disabled = status === "uploading" || done;
    submitBtn.textContent =
      status === "error" ? "Retry upload" : done ? "Uploaded" : status === "uploading" ? "Uploading…" : "Upload & extract";
  }

  async function start() {
    const file = getPendingFile();
    if (!file) {
      error = "The selected file is no longer in memory. Please pick it again.";
      status = "error";
      renderState();
      return;
    }
    status = "uploading";
    error = null;
    pct = 0;
    renderState();
    abort = new AbortController();
    try {
      const { jobId } = await uploadSyllabus(
        file,
        (p) => {
          pct = p;
          renderState();
        },
        abort.signal,
      );
      setJobId(jobId);
      status = "done";
      renderState();
      setTimeout(() => navigate("/extracting"), 600);
    } catch (e) {
      status = "error";
      error = e instanceof Error ? e.message : "Upload failed";
      renderState();
    }
  }

  submitBtn.addEventListener("click", start);
  renderState();

  return () => abort?.abort();
}
