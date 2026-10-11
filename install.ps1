# install.ps1 - one-shot installer. Creates backend\.venv and installs
# EVERYTHING the app needs in one go:
#
#   1. CPU-only PyTorch        (RAG embeddings, without the CUDA bloat)
#   2. backend\requirements.txt (fastapi, faiss, spacy, pytest, reportlab...)
#   3. the spaCy English model  (en_core_web_sm - better syllabus parsing)
#   4. the MiniLM embedding model (~80MB - pre-cached so the first upload
#      isn't the thing that waits on a download)
#   5. backend\.env             (only if you don't already have one)
#   6. uploads\ directory
#
# Then it verifies each piece and prints a status table. It does NOT start
# any server - use run.cmd for that, or see README.md "How to run it".
#
# Every step that needs the network degrades gracefully: the app is
# designed to work without RAG, without the spaCy model, and without an
# LLM, so a failed optional step is reported as DEGRADED, not fatal.
#
# Double-click install.cmd to run this, or from PowerShell:  .\install.ps1

$ErrorActionPreference = "Continue"   # we check and report each step ourselves

$root    = $PSScriptRoot
$backend = Join-Path $root "backend"

function Write-Step($text) {
    Write-Host ""
    Write-Host ">> $text" -ForegroundColor Cyan
}

# Runs a snippet with the venv's python, discarding BOTH streams, and
# returns $true only on exit code 0.
#
# The redirection is handed to cmd rather than written as `2>$null` in
# PowerShell: Windows PowerShell 5.1 turns a native command's stderr into
# NativeCommandError records, which (with $ErrorActionPreference set to
# Continue) get printed as red error text. Several of these checks are
# EXPECTED to fail on a machine with no network - a missing spaCy model
# would have dumped a multi-line SSL traceback in red right before the
# friendly "[DEGRADED]" line explaining it was fine. The snippet goes to a
# temp file so there is no quoting to get wrong.
function Invoke-Quiet($code) {
    $tmp = [System.IO.Path]::Combine([System.IO.Path]::GetTempPath(), "nsya-check-$([guid]::NewGuid().ToString('N')).py")
    try {
        Set-Content -Path $tmp -Value $code -Encoding utf8
        & cmd /c "`"$venvPython`" `"$tmp`" >nul 2>nul"
        return ($LASTEXITCODE -eq 0)
    } finally {
        Remove-Item $tmp -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "==================================================================" -ForegroundColor Green
Write-Host " NSYA installer" -ForegroundColor Green
Write-Host " Project root: $root"
Write-Host "==================================================================" -ForegroundColor Green

if (-not (Test-Path (Join-Path $backend "app\main.py"))) {
    Write-Host ""
    Write-Host "ERROR: Could not find backend\app\main.py under:" -ForegroundColor Red
    Write-Host "  $backend" -ForegroundColor Red
    Write-Host "This script must live directly inside the project folder" -ForegroundColor Red
    Write-Host "(the one that directly contains 'backend' and 'nsya-frontend')." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

# ---------------------------------------------------------------- venv ----
$venvPython = Join-Path $backend ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Step "Creating virtual environment (backend\.venv)..."
    Push-Location $backend
    python -m venv .venv
    if (-not (Test-Path $venvPython)) {
        Write-Host "   'python' didn't work, trying 'py' instead..." -ForegroundColor Yellow
        py -m venv .venv
    }
    Pop-Location
} else {
    Write-Step "Virtual environment already exists - reusing backend\.venv"
}

if (-not (Test-Path $venvPython)) {
    Write-Host ""
    Write-Host "ERROR: could not create a virtual environment. Is Python installed and on PATH?" -ForegroundColor Red
    Write-Host "Check with: python --version   (or)   py --version" -ForegroundColor Red
    Write-Host "Python 3.10 or newer is recommended." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

& $venvPython --version

Write-Step "Upgrading pip..."
& $venvPython -m pip install -q --upgrade pip

# --------------------------------------------------------------- torch ----
# CPU-only PyTorch BEFORE the rest of requirements. sentence-transformers
# (used for RAG embeddings) otherwise pulls a CUDA-enabled build that tries
# to grab NVIDIA GPU libraries even on a machine with no GPU - several extra
# gigabytes, and it can outright fail to import.
Write-Step "Installing CPU-only PyTorch (for RAG embeddings)..."
& $venvPython -m pip install -q torch --index-url https://download.pytorch.org/whl/cpu
if ($LASTEXITCODE -ne 0) {
    Write-Host "   Couldn't reach download.pytorch.org - falling back to the default index." -ForegroundColor Yellow
    & $venvPython -m pip install -q torch
}

# -------------------------------------------------------- requirements ----
Write-Step "Installing backend requirements (fastapi, faiss, spacy, pytest, reportlab...)..."
& $venvPython -m pip install -r (Join-Path $backend "requirements.txt")
$reqExit = $LASTEXITCODE
if ($reqExit -ne 0) {
    Write-Host ""
    Write-Host "ERROR: installing requirements.txt failed. The output above says why." -ForegroundColor Red
    Write-Host "Nothing else will work until this succeeds." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

# ---------------------------------------------------------- spacy model ----
# parser.py prefers en_core_web_sm and falls back to a blank English
# pipeline with a sentencizer if it's missing, so this is an improvement,
# not a requirement.
Write-Step "Downloading the spaCy English model (en_core_web_sm)..."
& cmd /c "`"$venvPython`" -m spacy download en_core_web_sm >nul 2>nul"
if ($LASTEXITCODE -ne 0) {
    Write-Host "   Could not download it (no network / blocked). Syllabus parsing will" -ForegroundColor Yellow
    Write-Host "   use the built-in fallback pipeline instead - everything still works." -ForegroundColor Yellow
} else {
    Write-Host "   Done." -ForegroundColor Green
}

# ------------------------------------------------------ embedding model ----
# Pre-cache MiniLM now rather than on the first upload, so nobody's first
# experience of the app is a silent 80MB download mid-pipeline.
Write-Step "Pre-downloading the MiniLM embedding model (~80MB, for RAG)..."
if (Invoke-Quiet "from sentence_transformers import SentenceTransformer`nSentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')") {
    Write-Host "   Done." -ForegroundColor Green
} else {
    Write-Host "   Could not download it. Retrieval will run keyword-only (BM25), which" -ForegroundColor Yellow
    Write-Host "   is a supported mode - the trust report says which one was used." -ForegroundColor Yellow
}

# ------------------------------------------------------------ .env/dirs ----
$envFile = Join-Path $backend ".env"
if (-not (Test-Path $envFile)) {
    Write-Step "Writing a default backend\.env..."
    Copy-Item (Join-Path $backend ".env.example") $envFile
    Write-Host "   Created backend\.env - edit it to add an LLM API key (optional)."
} else {
    Write-Step "backend\.env already exists - leaving it alone."
}

New-Item -ItemType Directory -Force -Path (Join-Path $backend "uploads") | Out-Null

# ------------------------------------------------------------- verify -----
# Check what actually works, rather than trusting that the steps above
# succeeded - a failure message can easily scroll past in a long log.
Write-Step "Verifying the installation..."

# Run these from the backend folder: that's where `import app.main`
# resolves, and where the app's own relative paths (./uploads, ./sya.db,
# ./faiss_indexes) point, exactly as when uvicorn runs there. Importing
# app.main also creates the database and uploads/ as a side effect, which
# is a real check that the schema can be built.
Push-Location $backend
$okApp    = Invoke-Quiet "import sys; sys.path.insert(0, '.'); import app.main"
$okRag    = Invoke-Quiet "import faiss, sentence_transformers"
$okSpacy  = Invoke-Quiet "import spacy; spacy.load('en_core_web_sm')"
$okTests  = Invoke-Quiet "import pytest, reportlab, httpx"
$okEmbed  = Invoke-Quiet "import sys; sys.path.insert(0, '.')`nfrom app.services.embeddings import embed_texts`nembed_texts(['warm up the model'])"
Pop-Location

function Status($ok, $goodText, $badText) {
    if ($ok) { Write-Host ("   [OK]       " + $goodText) -ForegroundColor Green }
    else     { Write-Host ("   [DEGRADED] " + $badText)  -ForegroundColor Yellow }
}

Write-Host ""
Write-Host "==================================================================" -ForegroundColor Green
Write-Host " Install finished." -ForegroundColor Green
Write-Host "==================================================================" -ForegroundColor Green

if (-not $okApp) {
    Write-Host "   [FAILED]   The backend itself does not import - see the errors above." -ForegroundColor Red
    Write-Host "              Try: backend\.venv\Scripts\python.exe -c ""import app.main""" -ForegroundColor Red
} else {
    Write-Host "   [OK]       Backend imports cleanly" -ForegroundColor Green
}
Status $okRag   "RAG installed (faiss + sentence-transformers)" "RAG libraries missing - retrieval falls back to keyword-only"
Status $okEmbed "Embedding model ready - vector search will be used"         "Embedding model unavailable - retrieval runs keyword-only (BM25)"
Status $okSpacy "spaCy English model installed"                              "spaCy model missing - parser uses its built-in fallback"
Status $okTests "Test dependencies installed (pytest, reportlab, httpx)"     "Test dependencies missing - 'pytest tests' may not run"

Write-Host ""
Write-Host " Nothing is running yet. To start the app:" -ForegroundColor Cyan
Write-Host "   double-click run.cmd        (starts backend + frontend together)"
Write-Host " or run the two commands manually - see README.md 'How to run it'."
Write-Host ""
Write-Host " Then open http://127.0.0.1:5500 and upload sample-syllabus.txt."
Write-Host ""
Write-Host " Optional extras:"
Write-Host "   install-ocr.cmd   OCR for scanned PDFs / photos of pages"
Write-Host "   backend\.env      add an LLM key for real generated lessons"
Write-Host "==================================================================" -ForegroundColor Green
Read-Host "Press Enter to close this window"
