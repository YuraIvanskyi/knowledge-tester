# Run all quality gates: ruff check, ruff format --check, pytest. Exits non-zero on any failure.
$ErrorActionPreference = "Continue"
Set-Location (Split-Path -Parent $PSScriptRoot)

# The environment is the repo-local .venv (uv default). To keep it elsewhere, e.g. outside a OneDrive folder, set UV_PROJECT_ENVIRONMENT.

$steps = @(
    @{ Name = "ruff check";          Args = @("ruff", "check", ".") },
    @{ Name = "ruff format --check"; Args = @("ruff", "format", "--check", ".") },
    @{ Name = "pytest";              Args = @("pytest") }
)

$failed = @()
foreach ($step in $steps) {
    Write-Host "== $($step.Name)" -ForegroundColor Cyan
    & python -m uv run @($step.Args)
    if ($LASTEXITCODE -ne 0) { $failed += $step.Name }
}

if ($failed.Count -gt 0) {
    Write-Host "FAILED: $($failed -join ', ')" -ForegroundColor Red
    exit 1
}
Write-Host "All checks passed." -ForegroundColor Green
exit 0
