---
id: KT-001
title: Bootstrap repository and tooling
phase: 0
type: chore
status: done
priority: must
size: S
depends_on: []
created: 2026-11-10
updated: 2026-11-11
---

# KT-001: Bootstrap repository and tooling

## Context
The folder already holds an empty git repository (branch `main`, no commits) with only `idea/` in it. Every later task needs a reproducible Python environment and quality tooling. See [plan.md §6](../plan.md#6-tech-stack) and [ADR-0001](../decisions/0001-django-server-rendered-htmx.md).

## Scope
- `.gitignore` covering Python caches, the virtual environment, `data/`, `*.sqlite3*`, `media/`, `.env`, `kt.toml`, `htmlcov/`, `.coverage`, `.pytest_cache/`, `.ruff_cache/` and `staticfiles/`.
- `.gitattributes` with `* text=auto` for consistent line endings on Windows. `.editorconfig` with UTF-8, LF, 4 spaces for Python and 2 for HTML/CSS/JS.
- A uv project:
  - `pyproject.toml` with `requires-python = ">=3.12"`, core dependencies (Django only for now), a `dev` dependency group, and placeholders for the optional extras listed in plan §6.2
  - a `.python-version` file pinning `3.13`
- Ruff configuration in `pyproject.toml`: line length 100, rules `E, F, I, UP, B, DJ, SIM`, ruff as the formatter.
- The virtual environment lives **outside OneDrive**. Document setting `UV_PROJECT_ENVIRONMENT` (for example to `%LOCALAPPDATA%\KnowledgeTester\venv`).

**Out of scope:** the Django project itself (KT-002) and pre-commit hooks, which are optional and can come later.

## Acceptance criteria
- [x] `uv sync` creates the environment, with Django installed, outside the OneDrive folder
- [x] `uv run ruff check .` and `uv run ruff format --check .` pass
- [x] `git status` doesn't show ignored artifacts after a sync and a test run
- [x] A stub `README.md` at the repository root links to `idea/plan.md` (the full README comes in KT-009)
- [x] First commit made, after the user approves

## Notes
- Pin exact versions through `uv.lock` and commit the lock file.

## Log
- 2026-11-10: created from the plan.
- 2026-11-11: implemented. `uv` was not installed; installed with `python -m pip install --user uv` (Scripts dir not on PATH, so use `python -m uv`). venv at `%LOCALAPPDATA%\KnowledgeTester\venv` via `UV_PROJECT_ENVIRONMENT` (set per session; `setx` documented in README). Django 6.0.10, ruff 0.17.4 locked. First commit approved and made.
