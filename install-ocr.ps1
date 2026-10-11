# install-ocr.ps1 - optional: installs OCR support (paddlepaddle +
# paddleocr) for scanned PDFs and image uploads. NOT part of the main
# install.ps1 - these are large packages (paddlepaddle alone is several
# hundred MB) only needed if you're uploading scanned documents with no
# real text layer. Everything else in the app works without this; a
# scanned upload without it now fails with a clear message telling you to
# run this script (see backend/app/services/ocr.py).
#
# run AFTER install.ps1 has already created backend\.venv:
#   .\install-ocr.ps1

$ErrorActionPreference = "Stop"

$root    = $PSScriptRoot
$backend = Join-Path $root "backend"
$venvPython = Join-Path $backend ".venv\Scripts\python.exe"
$venvPip = Join-Path $backend ".venv\Scripts\pip.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "ERROR: backend\.venv not found. Run install.ps1 first, then run this script." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "Installing OCR support (paddlepaddle + paddleocr)..."
Write-Host "This is a genuinely large download (several hundred MB) - it'll take a while."
& $venvPip install -q paddlepaddle paddleocr

Write-Host ""
Write-Host "Verifying..."
& $venvPython -c "import paddleocr" 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "OCR support installed and verified. Scanned PDFs and image uploads will now work." -ForegroundColor Green
} else {
    Write-Host "Install finished but paddleocr still doesn't import cleanly - check the pip output above for errors." -ForegroundColor Red
}
Read-Host "Press Enter to close this window"
