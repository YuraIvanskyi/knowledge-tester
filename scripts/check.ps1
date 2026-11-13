# Run all quality gates: ruff check, ruff format --check, pytest. Exits non-zero on any failure.
$ErrorActionPreference = "Continue"
Set-Location (Split-Path -Parent $PSScriptRoot)

# The environment is the repo-local .venv (uv default). To keep it elsewhere, e.g. outside a OneDrive folder, set UV_PROJECT_ENVIRONMENT.

# uv: the executable if it is on PATH, else "python -m uv" (a pip-installed uv).
if (Get-Command uv -ErrorAction SilentlyContinue) { $uv = @("uv") } else { $uv = @("python", "-m", "uv") }
function Invoke-Uv {
    $rest = @($uv | Select-Object -Skip 1)
    & $uv[0] @rest @args
}

$steps = @(
    @{ Name = "ruff check";          Args = @("ruff", "check", ".") },
    @{ Name = "ruff format --check"; Args = @("ruff", "format", "--check", ".") },
    @{ Name = "pytest";              Args = @("pytest") }
)

$failed = @()
foreach ($step in $steps) {
    Write-Host "== $($step.Name)" -ForegroundColor Cyan
    Invoke-Uv run @($step.Args)
    if ($LASTEXITCODE -ne 0) { $failed += $step.Name }
}

if ($failed.Count -gt 0) {
    Write-Host "FAILED: $($failed -join ', ')" -ForegroundColor Red
    exit 1
}
Write-Host "All checks passed." -ForegroundColor Green
exit 0
