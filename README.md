# Knowledge Tester

A local, offline-first "Google Forms for classrooms": teachers build tests, share them over the local network by link or QR code, get answers graded automatically, and print lean PDF sheets of the results.

Planning, architecture and progress live in [idea/](idea/). Start with [idea/plan.md](idea/plan.md); status is tracked in [idea/BOARD.md](idea/BOARD.md).

## Development setup (temporary, full README comes in KT-009)

Requires [uv](https://docs.astral.sh/uv/). Keep the virtual environment **outside OneDrive** so package files don't get synced:

```powershell
$env:UV_PROJECT_ENVIRONMENT = "$env:LOCALAPPDATA\KnowledgeTester\venv"
uv sync
uv run ruff check .
uv run ruff format --check .
```

Set `UV_PROJECT_ENVIRONMENT` permanently with `setx UV_PROJECT_ENVIRONMENT "%LOCALAPPDATA%\KnowledgeTester\venv"` (takes effect in new terminals).
