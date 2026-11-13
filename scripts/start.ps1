# One-click start: sync dependencies, migrate, serve on the LAN.
# Usage: scripts\start.ps1 [-Port 8000]
param([int]$Port = 8000)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

# uv: the executable if it is on PATH, else "python -m uv" (a pip-installed uv).
if (Get-Command uv -ErrorAction SilentlyContinue) { $uv = @("uv") } else { $uv = @("python", "-m", "uv") }
function Invoke-Uv {
    $rest = @($uv | Select-Object -Skip 1)
    & $uv[0] @rest @args
}

# The environment is the repo-local .venv (uv default). To keep it elsewhere, e.g. outside a OneDrive folder, set UV_PROJECT_ENVIRONMENT.

Invoke-Uv sync --extra xlsx
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Invoke-Uv run manage.py migrate
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Invoke-Uv run manage.py serve --port $Port
exit $LASTEXITCODE
