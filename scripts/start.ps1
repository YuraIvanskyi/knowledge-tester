# One-click start: sync dependencies, migrate, serve on the LAN.
# Usage: scripts\start.ps1 [-Port 8000]
param([int]$Port = 8000)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

# Keep the virtual environment outside OneDrive (thousands of small files would be synced).
if (-not $env:UV_PROJECT_ENVIRONMENT) {
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $env:LOCALAPPDATA "KnowledgeTester\venv"
}

python -m uv sync
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m uv run manage.py migrate
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m uv run manage.py serve --port $Port
exit $LASTEXITCODE
