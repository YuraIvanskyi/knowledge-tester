---
id: KT-002
title: Create the Django project skeleton and app layout
phase: 0
type: chore
status: done
priority: must
size: M
depends_on: [KT-001]
created: 2026-11-10
updated: 2026-11-13
---

# KT-002: Create the Django project skeleton and app layout

## Context
This sets up the code layout every later phase builds on. See [plan.md §7](../plan.md#7-repository-layout-and-django-apps) for the repository tree, app responsibilities, URL map and the dependency-direction rules.

## Scope
- A `config/` project with a settings package:
  - `base.py`
  - `dev.py` (DEBUG, debug toolbar)
  - `lan.py` (DEBUG off, used by `serve`)
- `apps/` with all nine apps created and registered: `core`, `accounts`, `assessments`, `exchange`, `delivery`, `grading`, `reports`, `roster` and `assistant`. Each gets a proper `AppConfig` and an empty `urls.py` where relevant.
- Top-level folders, each with a `.gitkeep` or README stub: `templates/`, `static/{css,js,vendor}/`, `assets/fonts/`, `locale/`, `schema/`, `docs/`, `scripts/`, `tests/`.
- A configuration loader in `config/settings/base.py`:
  - resolves the data folder (the logic itself is in KT-004)
  - reads `kt.toml` from the data folder with `tomllib`
  - lets `KT_*` environment variables override values
  - generates `SECRET_KEY` on first run and saves it to `kt.toml`
- Skeleton URL routing: `/`, `/teach/`, `/manage/`, `/django-admin/` and `/healthz`, with placeholder views where needed.
- `apps/grading/` and `apps/exchange/document.py` carry a module docstring: "no Django imports allowed here".

**Out of scope:** the User model (KT-003, which must be configured before the first `migrate`) and UI styling (KT-006).

## Acceptance criteria
- [x] `uv run manage.py check` passes with both `dev` and `lan` settings
- [x] `uv run manage.py check --deploy --settings=config.settings.lan` shows only the documented HTTPS warnings, which are accepted because the LAN uses plain HTTP (ADR-0003)
- [x] The first start creates `kt.toml` with a random `SECRET_KEY`, and later starts reuse it
- [x] A table in the README (or the KT-009 draft) lists the `KT_*` settings: `KT_DATA_DIR`, `KT_PORT`, `KT_DEBUG`, `KT_ALLOWED_HOSTS`, `KT_SETTINGS`

## Notes
- **Don't run `migrate` until KT-003 has set `AUTH_USER_MODEL`.**

## Log
- 2026-11-10: created from the plan.
- 2026-11-13: checked: `manage.py check` clean with dev and lan; `check --deploy` shows only W004/W008/W012/W016 (HTTPS, accepted); `apps/core/tests/test_config_file.py` covers the generated key; the README has a settings table (the real variables are `KT_DATA_DIR`, `KT_SECRET_KEY`; the port is a `serve` option, not `KT_PORT`).
