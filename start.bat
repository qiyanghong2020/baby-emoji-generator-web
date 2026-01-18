@echo off
setlocal enabledelayedexpansion

set PORT=%1
if "%PORT%"=="" set PORT=8000

set VENV_PY=%~dp0backend\.venv\Scripts\python.exe
set REQ=%~dp0backend\requirements.txt

if not exist "%VENV_PY%" (
  python -m venv "%~dp0backend\.venv"
)

"%VENV_PY%" -m pip install -r "%REQ%"
"%VENV_PY%" -m uvicorn app.main:app --app-dir "%~dp0backend" --reload --host 0.0.0.0 --port %PORT%

