@echo off
REM Double-click this to start the app: backend (port 8000) + frontend
REM (port 5500), each in its own window, then opens your browser.
REM Run install.cmd first.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1"
