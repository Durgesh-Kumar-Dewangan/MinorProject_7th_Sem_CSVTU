import { renderShell } from "../shell.js";
import { Icon } from "../icons.js";
import { el, toast } from "../utils.js";
import { setPendingFile } from "../store.js";
import { navigate } from "../router.js";

// Mirrors ALLOWED_EXTENSIONS in backend/app/api/routers/syllabus.py.
const ALLOWED_EXTENSIONS = [".pdf", ".txt", ".png", ".jpg", ".jpeg"];

export function renderIngest(root) {
  document.title = "NSYA.AI — Turn any syllabus into a learning path";

  const page = renderShell(root, { active: "upload", center: true, width: "md" });

  function accept(file) {
    if (!file) return;
    // The file picker's `accept` only filters the browse dialog - a
    // drag-and-dropped file bypasses it entirely. Checking here means an
    // unsupported file is refused with a readable message on this screen,
    // instead of sailing through to the upload screen and coming back as a
    // raw 400 from the backend.
    const name = (file.name || "").toLowerCase();
    if (!ALLOWED_EXTENSIONS.some((ext) => name.endsWith(ext))) {
      toast(`"${file.name}" isn't a supported syllabus file. Use a PDF, TXT, PNG or JPG.`, { error: true });
      return;
    }
    setPendingFile(file);
    navigate("/uploading");
  }

  // Kept in lockstep with ALLOWED_EXTENSIONS in
  // backend/app/api/routers/syllabus.py - offering a type the backend
  // rejects just moves the failure to a 400 after the upload screen.
  // .doc/.docx are NOT here: nothing in the backend extracts Word text.
  const input = el("input", {
    type: "file",
    accept: ".pdf,.txt,.png,.jpg,.jpeg",
    class: "hidden",
    onchange: (e) => accept(e.target.files?.[0]),
  });

  const dropzone = el(
    "div",
    {
      class: "ingest__dropzone",
      ondragover: (e) => {
        e.preventDefault();
        dropzone.classList.add("is-over");
      },
      ondragleave: () => dropzone.classList.remove("is-over"),
      ondrop: (e) => {
        e.preventDefault();
        dropzone.classList.remove("is-over");
        accept(e.dataTransfer.files?.[0]);
      },
    },
    [
      el("div", { class: "ingest__ring-outer nsya-ring-outer" }),
      el("div", { class: "ingest__ring-inner nsya-ring-inner" }),
      el("div", { class: "ingest__ring-pulse nsya-pulse-ring" }),
      el(
        "button",
        { type: "button", class: "ingest__button", onclick: () => input.click() },
        [
          el("span", { html: Icon.uploadCloud("", 44) }),
          el("span", {}, "Drop or choose your syllabus"),
        ],
      ),
      input,
    ],
  );

  const copy = el("div", { class: "ingest__copy nsya-rise" }, [
    el("h1", {}, "Ingest your syllabus"),
    el(
      "p",
      {},
      "PDF, TXT or a photo of the page (PNG/JPG). Your file is sent to your own processing backend, which returns the subjects, units and topics.",
    ),
    el("p", { class: "ingest__badge" }, [
      el("span", { html: Icon.fileText("", 14) }),
      "Nothing is sent until you confirm the upload",
    ]),
  ]);

  const wrap = el("div", { class: "ingest" }, [dropzone, copy]);
  page.appendChild(wrap);
}
