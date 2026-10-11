#!/usr/bin/env bash
# One-shot installer (Mac/Linux). Creates backend/.venv and installs
# EVERYTHING the app needs in one go:
#
#   1. CPU-only PyTorch         (RAG embeddings, without the CUDA bloat)
#   2. backend/requirements.txt (fastapi, faiss, spacy, pytest, reportlab...)
#   3. the spaCy English model  (en_core_web_sm - better syllabus parsing)
#   4. the MiniLM embedding model (~80MB - pre-cached so the first upload
#      isn't the thing that waits on a download)
#   5. backend/.env             (only if you don't already have one)
#   6. uploads/ directory
#
# Then it verifies each piece and prints a status table. It does NOT start
# any server - use ./run.sh for that, or see README.md "How to run it".
#
# Every step that needs the network degrades gracefully: the app is
# designed to work without RAG, without the spaCy model and without an LLM,
# so a failed optional step is reported as DEGRADED, not fatal.
#
# run with:  bash install.sh    (or  ./install.sh  after chmod +x)
set -u
cd "$(dirname "$0")"

ROOT="$(pwd)"
BACKEND="$ROOT/backend"

step() { printf '\n>> %s\n' "$1"; }

echo "=================================================================="
echo " NSYA installer"
echo " Project root: $ROOT"
echo "=================================================================="

if [ ! -f "$BACKEND/app/main.py" ]; then
  echo "ERROR: could not find backend/app/main.py under $BACKEND"
  echo "Run this script from inside the project folder (the one that"
  echo "directly contains 'backend' and 'nsya-frontend')."
  exit 1
fi

# ---------------------------------------------------------------- venv ----
PY="$BACKEND/.venv/bin/python3"
if [ ! -x "$PY" ]; then
  step "Creating virtual environment (backend/.venv)..."
  (cd "$BACKEND" && python3 -m venv .venv)
else
  step "Virtual environment already exists - reusing backend/.venv"
fi

if [ ! -x "$PY" ]; then
  echo "ERROR: could not create a virtual environment. Is python3 installed?"
  echo "Check with: python3 --version   (Python 3.10+ recommended)"
  exit 1
fi

"$PY" --version

step "Upgrading pip..."
"$PY" -m pip install -q --upgrade pip

# --------------------------------------------------------------- torch ----
# CPU-only PyTorch BEFORE the rest of requirements - sentence-transformers
# otherwise pulls a CUDA build that drags in NVIDIA libraries even with no
# GPU present (several extra GB, and it can fail to import).
step "Installing CPU-only PyTorch (for RAG embeddings)..."
if ! "$PY" -m pip install -q torch --index-url https://download.pytorch.org/whl/cpu; then
  echo "   Couldn't reach download.pytorch.org - falling back to the default index."
  "$PY" -m pip install -q torch || true
fi

# -------------------------------------------------------- requirements ----
step "Installing backend requirements (fastapi, faiss, spacy, pytest, reportlab...)..."
if ! "$PY" -m pip install -r "$BACKEND/requirements.txt"; then
  echo ""
  echo "ERROR: installing requirements.txt failed. The output above says why."
  echo "Nothing else will work until this succeeds."
  exit 1
fi

# ---------------------------------------------------------- spacy model ----
# parser.py prefers en_core_web_sm and falls back to a blank English
# pipeline with a sentencizer if it's missing - an improvement, not a need.
step "Downloading the spaCy English model (en_core_web_sm)..."
if ! "$PY" -m spacy download en_core_web_sm >/dev/null 2>&1; then
  echo "   Could not download it (no network / blocked). Syllabus parsing will"
  echo "   use the built-in fallback pipeline instead - everything still works."
fi

# ------------------------------------------------------ embedding model ----
# Pre-cache MiniLM now rather than mid-pipeline on the first upload.
step "Pre-downloading the MiniLM embedding model (~80MB, for RAG)..."
if ! "$PY" -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')" >/dev/null 2>&1; then
  echo "   Could not download it. Retrieval will run keyword-only (BM25), which"
  echo "   is a supported mode - the trust report says which one was used."
fi

# ------------------------------------------------------------ .env/dirs ----
if [ ! -f "$BACKEND/.env" ]; then
  step "Writing a default backend/.env..."
  cp "$BACKEND/.env.example" "$BACKEND/.env"
  echo "   Created backend/.env - edit it to add an LLM API key (optional)."
else
  step "backend/.env already exists - leaving it alone."
fi

mkdir -p "$BACKEND/uploads"

# ------------------------------------------------------------- verify -----
# Check what actually works rather than trusting the steps above - a
# failure message is easy to miss in a long install log.
step "Verifying the installation..."

# Run from the backend folder: that's where `import app.main` resolves and
# where the app's relative paths (./uploads, ./sya.db, ./faiss_indexes)
# point, exactly as when uvicorn runs there.
cd "$BACKEND"
check() { "$PY" -c "$1" >/dev/null 2>&1 && echo yes || echo no; }

OK_APP=$(check "import app.main")
OK_RAG=$(check "import faiss, sentence_transformers")
OK_SPACY=$(check "import spacy; spacy.load('en_core_web_sm')")
OK_TESTS=$(check "import pytest, reportlab, httpx")
OK_EMBED=$(check "from app.services.embeddings import embed_texts; embed_texts(['warm up the model'])")
cd "$ROOT"

status() {  # status <yes|no> <good> <bad>
  if [ "$1" = "yes" ]; then printf '   [OK]       %s\n' "$2"; else printf '   [DEGRADED] %s\n' "$3"; fi
}

echo ""
echo "=================================================================="
echo " Install finished."
echo "=================================================================="
if [ "$OK_APP" = "yes" ]; then
  echo "   [OK]       Backend imports cleanly"
else
  echo "   [FAILED]   The backend itself does not import - see the errors above."
  echo "              Try: backend/.venv/bin/python3 -c 'import app.main'"
fi
status "$OK_RAG"   "RAG installed (faiss + sentence-transformers)" "RAG libraries missing - retrieval falls back to keyword-only"
status "$OK_EMBED" "Embedding model ready - vector search will be used" "Embedding model unavailable - retrieval runs keyword-only (BM25)"
status "$OK_SPACY" "spaCy English model installed" "spaCy model missing - parser uses its built-in fallback"
status "$OK_TESTS" "Test dependencies installed (pytest, reportlab, httpx)" "Test dependencies missing - 'pytest tests' may not run"

cat <<'EOF'

 Nothing is running yet. To start the app:
   bash run.sh                (starts backend + frontend together)
 or run the two commands manually - see README.md "How to run it".

 Then open http://127.0.0.1:5500 and upload sample-syllabus.txt.

 Optional extras:
   bash install-ocr.sh        OCR for scanned PDFs / photos of pages
   backend/.env               add an LLM key for real generated lessons
==================================================================
EOF
