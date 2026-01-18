param(
  [int]$Port = 8000,
  [string]$Host = "0.0.0.0"
)

$ErrorActionPreference = "Stop"

$venvPython = Join-Path $PSScriptRoot "backend\.venv\Scripts\python.exe"
$requirements = Join-Path $PSScriptRoot "backend\requirements.txt"

if (-not (Test-Path $venvPython)) {
  python -m venv (Join-Path $PSScriptRoot "backend\.venv")
}

& $venvPython -m pip install -r $requirements | Out-Host

& $venvPython -m uvicorn app.main:app --app-dir (Join-Path $PSScriptRoot "backend") --reload --host $Host --port $Port

