# One-click start: sync dependencies, migrate, serve on the LAN.
# Usage: scripts\start.ps1 [-Port 8000]
param([int]$Port = 8000)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

# The environment is the repo-local .venv (uv default). To keep it elsewhere, e.g. outside a OneDrive folder, set UV_PROJECT_ENVIRONMENT.

python -m uv sync
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m uv run manage.py migrate
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m uv run manage.py serve --port $Port
exit $LASTEXITCODE
