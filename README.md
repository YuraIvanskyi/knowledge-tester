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

pytest uses `config.settings.test`, which sets English as the default language so that older tests can assert English text. The application itself (`dev`, `lan`) defaults to Ukrainian. Tests of Ukrainian behaviour select it explicitly (see `apps/core/tests/test_i18n.py`).

`tests/test_offline.py` renders key pages and scans `static/` for external URLs, inline `<style>`, `style=`, inline scripts and `on*=` handlers (the CSP is `default-src 'self'`). Add new pages to `page_responses` there.

## Translations (Ukrainian is the default)

The UI language is **Ukrainian (`uk`)**; English (`en`) is the second language. Nothing is detected from the browser: a phone with an English browser still gets Ukrainian until the user presses "English" in the page footer. The choice is stored in a cookie by Django's `set_language` view (`/i18n/setlang/`); `apps.core.middleware.DefaultLanguageMiddleware` drops `Accept-Language` while there is no cookie. The names "Українська" and "English" are never translated.

**GNU gettext is not needed.** The catalog is `locale/uk/LC_MESSAGES/django.po` and the compiled `django.mo` is committed. `scripts/i18n.py` (logic in `apps/core/i18n_tools.py`, built on `polib`, a dev dependency) replaces `makemessages` / `compilemessages`:

```powershell
python -m uv run python scripts/i18n.py extract                 # scan templates/, apps/, config/ -> update django.po (keeps msgstr, marks dropped strings obsolete)
python -m uv run python scripts/i18n.py merge locale/uk/parts   # fill empty msgstr from *.po fragments; reports unmatched entries and conflicts (--overwrite replaces)
python -m uv run python scripts/i18n.py check                   # exit 1 on untranslated/fuzzy entries or %(name)s / %s mismatches
python -m uv run python scripts/i18n.py compile                 # django.po -> django.mo (commit both)
```

Workflow for a new or changed string: wrap it, run `extract`, translate the empty `msgstr` in `django.po` (or in a fragment, then `merge`), run `check`, then `compile`. A literal `%` inside `{% translate %}` text is not supported by `extract`; avoid it. Python strings under `tests/`, `migrations/` and in `test_*.py` are not collected.

Optionally, if you install real GNU gettext (on Windows, for example from the "GNU gettext for Windows" builds or MSYS2) you can also run `python -m uv run manage.py makemessages -l uk` and `compilemessages`; the scripts above are the supported route and use the same file format. Adding a language means adding it to `LANGUAGES`, its plural rule to `PLURAL_FORMS` in `i18n_tools.py`, and running `extract -l xx`.

Rules for contributors:

- Wrap every user-visible string: `{% translate %}` / `{% blocktranslate %}` in templates, `gettext` in views and `gettext_lazy` for module-level strings (model `choices`, form labels). This includes `aria-label`, `title`, `placeholder`, flash messages and error messages shown to users.
- Anything with a count goes through `ngettext` / `{% blocktranslate count n=... %}...{% plural %}...{% endblocktranslate %}`. Ukrainian has **three** plural forms (1, 2-4, 5+, with 11-14 taking the last), so never write `"item" if n == 1 else "items"` and never build sentences from fragments.
- Use named placeholders (`%(name)s`) so word order can change, and `pgettext` / `{% translate "..." context "..." %}` when one English word needs different translations (for example "Open" as an adjective versus a verb).
- Do not translate test content, only the interface.

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
scripts/           check.ps1, start.ps1, i18n.py (translation catalog tooling)
locale/            uk/LC_MESSAGES/django.po + django.mo
tests/             cross-app tests (smoke, offline guard)
idea/              plan, ADRs, issues, board
```

## Conventions

- UI rules (plan section 17): system fonts, one accent colour, no gradients or shadows, radius at most 6px, no emoji, tap targets of 44px, inputs of 16px or more. The CSS vocabulary is documented in the contracts file.
- No inline styles or scripts (CSP). Wrap user-visible strings for translation (see Translations).
- Every teacher view needs `@login_required` and an ownership check.
- Run `scripts\check.ps1` before committing.
