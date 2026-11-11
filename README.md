# Knowledge Tester

A local, offline-first "Google Forms for classrooms": teachers import or build tests, share them over the local network by link or QR code, get answers graded automatically, review open answers and export results. Students need only a phone browser.

Planning, architecture and progress live in [idea/](idea/). Start with [idea/plan.md](idea/plan.md); status is in [idea/BOARD.md](idea/BOARD.md). Prototype contracts: [idea/specs/prototype-contracts.md](idea/specs/prototype-contracts.md).

## Requirements

- Windows 10/11 (Linux and macOS also work), Python 3.12+, [uv](https://docs.astral.sh/uv/) (run as `python -m uv` if it is not on PATH).
- No internet is needed at run time: there are no CDNs, web fonts or external calls.

## Setup

Keep the virtual environment **outside OneDrive**, otherwise thousands of package files get synced:

```powershell
$env:UV_PROJECT_ENVIRONMENT = "$env:LOCALAPPDATA\KnowledgeTester\venv"   # setx to make it permanent
python -m uv sync
python -m uv run manage.py migrate
python -m uv run manage.py seed_demo      # demo users: teacher/teacher and admin/admin
```

(`seed_demo` is provided by the assessments/delivery work; without it use `python -m uv run manage.py createsuperuser`.)

Data (database, `kt.toml` with the generated secret key, media) lives in `%LOCALAPPDATA%\KnowledgeTester\` (`~/.local/share/knowledge-tester/` elsewhere). Override with `KT_DATA_DIR`. `serve` warns if that folder is inside OneDrive, Dropbox or Google Drive, because sync clients can corrupt SQLite.

## Running

```powershell
python -m uv run manage.py runserver        # development only, http://127.0.0.1:8000
python -m uv run manage.py serve            # LAN mode (Waitress, DEBUG off)
scripts\start.ps1                           # sync + migrate + serve in one go
```

`serve [--port 8000] [--host 0.0.0.0] [--threads 8] [--no-qr]` prints the data folder, every LAN URL and a QR code of the first one. Stop it with Ctrl+C. `/healthz` answers `ok`.

## Opening it from phones

1. Put the host and phones on the same network (a portable Wi-Fi router without internet is the most reliable; phone hotspots often cap at about 10 clients; school Wi-Fi often has client isolation, which blocks device-to-device traffic).
2. Set the Windows network profile to **Private**.
3. Allow the port once, in PowerShell as administrator:
   `New-NetFirewallRule -DisplayName "Knowledge Tester" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Private`
4. Disable sleep during the lesson and keep the laptop on mains power.
5. Scan the QR code from the terminal (or from a session's share screen), or type the URL.

## Checks and tests

```powershell
scripts\check.ps1                            # ruff check, ruff format --check, pytest
python -m uv run pytest apps/core apps/accounts tests
```

`tests/test_offline.py` renders key pages and scans `static/` for external URLs, inline `<style>`, `style=`, inline scripts and `on*=` handlers (the CSP is `default-src 'self'`). Add new pages to `page_responses` there.

## Layout

```
config/            Django project (settings: base, dev, lan)
apps/core/         landing, dashboard, healthz, `serve` command, LAN/IP helpers
apps/accounts/     custom User (admin/teacher roles), login and logout
apps/assessments/  projects and tests (Test Document JSON), publishing
apps/exchange/     JSON import/export and validation
apps/delivery/     sessions, share/QR screen, taker flow
apps/grading/      pure scoring engine and grade scales
apps/reports/      results, review of open answers, CSV
templates/         shared templates (base.html is the UI kit shell)
static/css/        base.css = UI kit (tokens, components, dark mode)
scripts/           check.ps1, start.ps1
tests/             cross-app tests (smoke, offline guard)
idea/              plan, ADRs, issues, board
```

## Conventions

- UI rules (plan section 17): system fonts, one accent colour, no gradients or shadows, radius at most 6px, no emoji, tap targets of 44px, inputs of 16px or more. The CSS vocabulary is documented in the contracts file.
- No inline styles or scripts (CSP). Wrap user-visible strings for translation.
- Every teacher view needs `@login_required` and an ownership check.
- Run `scripts\check.ps1` before committing.
