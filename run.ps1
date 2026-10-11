# run.ps1 - starts both halves of the app and opens the browser.
#
#   backend   uvicorn on 127.0.0.1:8000   (FastAPI, docs at /docs)
#   frontend  python -m http.server 5500  (static files, no build step)
#
# 5500 is the port the backend's default CORS_ORIGINS allows, and 8000 is
# what nsya-frontend/index.html points window.NSYA_API_URL at - change one
# and you have to change the other.
#
# Each server runs in its own window so you can watch its log and close it
# independently. Run install.cmd first.
#
# Double-click run.cmd, or from PowerShell:  .\run.ps1

$ErrorActionPreference = "Stop"

$root    = $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "nsya-frontend"
$venvPython = Join-Path $backend ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "ERROR: backend\.venv not found. Run install.cmd first." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

function Test-PortBusy($port) {
    # An already-listening port means that server is probably already up;
    # starting a second one would just fail with "address in use" in a
    # window that then closes too fast to read.
    $conn = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
    return $null -ne $conn
}

if (Test-PortBusy 8000) {
    Write-Host "Port 8000 is already in use - assuming the backend is already running." -ForegroundColor Yellow
} else {
    Write-Host "Starting backend on http://127.0.0.1:8000 ..." -ForegroundColor Cyan
    Start-Process -FilePath $venvPython `
        -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000" `
        -WorkingDirectory $backend
}

if (Test-PortBusy 5500) {
    Write-Host "Port 5500 is already in use - assuming the frontend is already running." -ForegroundColor Yellow
} else {
    Write-Host "Starting frontend on http://127.0.0.1:5500 ..." -ForegroundColor Cyan
    Start-Process -FilePath $venvPython `
        -ArgumentList "-m", "http.server", "5500" `
        -WorkingDirectory $frontend
}

# Give uvicorn a moment to bind before the browser asks for the page.
Start-Sleep -Seconds 3

Write-Host ""
Write-Host "==================================================================" -ForegroundColor Green
Write-Host " NSYA is running:" -ForegroundColor Green
Write-Host "   app       http://127.0.0.1:5500"
Write-Host "   API docs  http://127.0.0.1:8000/docs"
Write-Host ""
Write-Host " Upload sample-syllabus.txt (one subject) or"
Write-Host " multi-subject-sample.txt (two subjects) to try it."
Write-Host ""
Write-Host " Close the two server windows to stop." -ForegroundColor Green
Write-Host "==================================================================" -ForegroundColor Green

Start-Process "http://127.0.0.1:5500"
