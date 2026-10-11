#!/usr/bin/env bash
# optional: installs OCR support (paddlepaddle + paddleocr) for scanned
# PDFs and image uploads. NOT part of the main install.sh - these are
# large packages (paddlepaddle alone is several hundred MB) only needed if
# you're uploading scanned documents with no real text layer. Everything
# else in the app works without this; a scanned upload without it now
# fails with a clear message telling you to run this script (see
# backend/app/services/ocr.py).
#
# run with:  bash install-ocr.sh   (after the main install.sh has already
# created backend/.venv)
set -e
cd "$(dirname "$0")"

BACKEND="./backend"
VENV_PYTHON="$BACKEND/.venv/bin/python3"

if [ ! -f "$VENV_PYTHON" ]; then
  echo "ERROR: backend/.venv not found. Run install.sh first, then run this script."
  exit 1
fi

echo "Installing OCR support (paddlepaddle + paddleocr)..."
echo "This is a genuinely large download (several hundred MB) - it'll take a while."
"$BACKEND/.venv/bin/pip" install -q paddlepaddle paddleocr

echo ""
echo "Verifying..."
if "$VENV_PYTHON" -c "import paddleocr" 2>/dev/null; then
  echo "OCR support installed and verified. Scanned PDFs and image uploads will now work."
else
  echo "Install finished but paddleocr still doesn't import cleanly - check the pip output above for errors."
  exit 1
fi
