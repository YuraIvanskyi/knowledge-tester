---
id: KT-008
title: Set up test harness and quality gates
phase: 0
type: chore
status: ready
priority: must
size: S
depends_on: [KT-002]
created: 2026-11-10
updated: 2026-11-10
---

# KT-008: Set up test harness and quality gates

## Context
Grading correctness and offline operation are the riskiest properties of this app, so the guards go in from the start. See [plan.md §20](../plan.md#20-quality).

## Scope
- `pytest`, `pytest-django`, `pytest-cov` and `model-bakery`, configured in `pyproject.toml` with `DJANGO_SETTINGS_MODULE` set for tests.
- Smoke tests:
  - `/` responds
  - `/healthz` returns 200
  - the login page renders
  - `/teach/` redirects anonymous users
- **Offline guard test.** It renders a list of key pages (extended in each phase) and scans every file under `static/`, then fails if any of them references an external `http(s)://` host. Allow-list only localhost and relative URLs.
- **Query-count helper** (a wrapper around `django_assert_max_num_queries`) for later taker-page tests.
- One-command checks:
  - `scripts/check.ps1` for Windows
  - `scripts/check.sh` for POSIX systems
  - each runs `ruff check`, `ruff format --check` and `pytest` with coverage

## Acceptance criteria
- [ ] `uv run pytest` is green and prints a coverage summary
- [ ] Adding `<script src="https://cdn.example.com/x.js">` to any template makes the offline guard test fail (checked once, then reverted)
- [ ] `scripts/check.ps1` exits non-zero when any check fails

## Log
- 2026-11-10: created from the plan.
