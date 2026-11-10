---
id: KT-004
title: Configure data folder and SQLite (WAL)
phase: 0
type: chore
status: ready
priority: must
size: S
depends_on: [KT-002]
created: 2026-11-10
updated: 2026-11-10
---

# KT-004: Configure data folder and SQLite (WAL)

## Context
The database must survive 40–60 takers submitting at once and must **never** live in a OneDrive-synced folder. See [ADR-0002](../decisions/0002-sqlite-wal-data-dir.md) and [plan.md §19.3](../plan.md#193-data-location-the-onedrive-caveat).

## Scope
- Data folder resolution, in this order:
  1. `KT_DATA_DIR`
  2. Windows: `%LOCALAPPDATA%\KnowledgeTester\`
  3. Other systems: `$XDG_DATA_HOME/knowledge-tester`, falling back to `~/.local/share/knowledge-tester`
- Create `media/`, `backups/` and `logs/` inside it automatically.
- At startup, warn if the resolved path contains `OneDrive`, `Dropbox` or `Google Drive`. Recognize OneDrive through the `OneDrive*` environment variables and a path check.
- SQLite settings:
  - `init_command` setting `journal_mode=WAL`, `synchronous=NORMAL` and `busy_timeout=5000`
  - `transaction_mode="IMMEDIATE"`
  - a connection `timeout` of about 20 seconds
- `MEDIA_ROOT` pointing at the data folder's `media/`.

## Acceptance criteria
- [ ] A test asserts that `PRAGMA journal_mode` returns `wal`
- [ ] A test with 20 threads doing concurrent short write transactions gets no "database is locked" errors
- [ ] A unit test confirms the warning fires for a path inside OneDrive
- [ ] The data folder location is printed at startup by `serve` (KT-005) and `runserver`

## Log
- 2026-11-10: created from the plan.
