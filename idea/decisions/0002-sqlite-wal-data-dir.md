# ADR-0002: SQLite in WAL mode, in a data folder outside the repository and OneDrive

- **Status:** Proposed (2026-11-10)
- **Related:** plan.md §7 (data location), §19.3, §19.4 · KT-004, KT-901

## Context

One host serves one classroom, with a realistic peak of 40–60 takers submitting small writes at about the same time. Teachers aren't system administrators, so installing a database server is out of scope. The repository currently sits in a OneDrive-synced folder, and sync clients lock and rewrite files, which can corrupt SQLite databases and their WAL files.

## Decision

- Use **SQLite** as the only database, configured with:
  - `journal_mode=WAL` and `synchronous=NORMAL`
  - `busy_timeout` of about 5 seconds
  - Django's SQLite `transaction_mode="IMMEDIATE"`, so write transactions don't hit "database is locked" when upgrading from read to write
- Keep all data (database, media, backups, logs, local configuration) in a **per-user data folder**: `%LOCALAPPDATA%\KnowledgeTester\` on Windows and `~/.local/share/knowledge-tester/` elsewhere. `KT_DATA_DIR` overrides it.
- At startup, **warn** if the data folder is inside OneDrive, Dropbox or Google Drive.
- Back up through SQLite's **online backup API**, never by copying a live file.

## Consequences

- **Easier:** zero setup, and a backup is one file plus `media/`. Tests are fast.
- **Harder:** only one writer at a time, so transactions must stay short. Grading and other heavy work happen outside the request's write transaction or in small steps. Scaling beyond one school building would need Postgres, which Django makes a contained change.
- **Commitment:** a load test (KT-310) checks concurrency on the target laptop before each milestone.

## Alternatives considered

- **PostgreSQL:** robust, but it's a service to install, run and upgrade on a teacher's laptop, which is overkill here.
- **Storing the database next to the code (`./data`):** simple, but unsafe while the repository lives in OneDrive.
