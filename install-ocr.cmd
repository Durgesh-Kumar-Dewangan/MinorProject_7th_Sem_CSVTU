@echo off
REM Optional: double-click this to install OCR support (paddlepaddle +
REM paddleocr) for scanned PDFs and image uploads. Run install.cmd FIRST -
REM this needs backend\.venv to already exist.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-ocr.ps1"
pause
