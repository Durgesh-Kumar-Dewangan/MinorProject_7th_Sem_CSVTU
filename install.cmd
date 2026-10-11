@echo off
REM ============================================================
REM  Double-click this ONCE to install everything the app needs:
REM  virtualenv, CPU-only PyTorch, all Python packages, the spaCy
REM  model, the MiniLM embedding model, and a default .env.
REM
REM  It does NOT start any server. When it finishes, double-click
REM  run.cmd to start the app (or see README.md "How to run it").
REM ============================================================
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
