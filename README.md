# Knowledge Tester

A local, offline-first "Google Forms for classrooms": teachers import or build tests, share them over the local network by link or QR code, get answers graded automatically, review open answers and export results. Students need only a phone browser.

**Teachers:** the short guide in Ukrainian is [docs/quick-start.uk.md](docs/quick-start.uk.md) (install, run a lesson, what to do when phones cannot connect). A prompt that turns a PDF textbook into an importable test: [docs/llm/test-from-textbook.uk.prompt.md](docs/llm/test-from-textbook.uk.prompt.md).

Planning, architecture and progress live in [idea/](idea/). Start with [idea/plan.md](idea/plan.md); status is in [idea/BOARD.md](idea/BOARD.md). Prototype contracts: [idea/specs/prototype-contracts.md](idea/specs/prototype-contracts.md).

## Requirements

- Windows 10/11 (Linux and macOS also work), Python 3.12+, [uv](https://docs.astral.sh/uv/) (run as `python -m uv` if it is not on PATH).
- No internet is needed at run time: there are no CDNs, web fonts or external calls.

## Quick start (Windows)

Install Python 3.12+, then double-click **`Start.cmd`**. It installs uv and the packages on the first run (internet needed once), backs up and updates the database, checks the firewall rule and the network profile (and offers to fix them, with elevation), starts the server and opens the browser. On a fresh data folder the browser shows the **first-run page**, where the first admin account is created (only reachable from the host computer; gone once any account exists). The rest of this file is for developers.

## Setup

`uv sync` creates the virtual environment in `.venv` inside the repository (git-ignored); VS Code picks it up automatically. If the repository lives in a OneDrive folder, keep the environment outside it instead, otherwise thousands of package files get synced: set `UV_PROJECT_ENVIRONMENT` (for example to `$env:LOCALAPPDATA\KnowledgeTester\venv`, `setx` makes it permanent) and select that interpreter in VS Code.

```powershell
python -m uv sync --extra xlsx                  # the xlsx extra (openpyxl) enables XLSX roster import
python -m uv run manage.py migrate
python -m uv run manage.py seed_demo      # demo users: teacher/teacher and admin/admin
```

Without `seed_demo` the first admin is created in the browser on the first-run page (`/accounts/setup/`, host computer only) or with `python -m uv run manage.py createsuperuser`; that admin then creates the teacher accounts in the browser at `/manage/`. Without the `xlsx` extra everything works except XLSX uploads (CSV and pasted lists still do).

Data (database, `kt.toml` with the generated secret key, media) lives in `%LOCALAPPDATA%\KnowledgeTester\` (`~/.local/share/knowledge-tester/` elsewhere). Override with `KT_DATA_DIR`. `serve` warns if that folder is inside OneDrive, Dropbox or Google Drive, because sync clients can corrupt SQLite.

## Running

```powershell
python -m uv run manage.py runserver        # development only, http://127.0.0.1:8000
python -m uv run manage.py serve            # LAN mode (Waitress, DEBUG off)
Start.cmd                                   # the launcher (double-click); same as scripts\start.ps1 [-Port 8000] [-NoBrowser] [-NoPrompt]
scripts\allow-phones.ps1 [-MakePrivate]     # firewall rule for the port (asks for elevation itself)
```

`serve [--port 8000] [--host 0.0.0.0] [--threads 8] [--no-qr] [--open]` collects the static files, makes a backup, prints the data folder, every LAN URL and a QR code of the first one; `--open` opens the teacher area in the host's browser. Stop it with Ctrl+C. `/healthz` answers `ok`.

`start.ps1` keeps the virtual environment out of a synced folder by itself (it sets `UV_PROJECT_ENVIRONMENT` when the repository is inside OneDrive, Dropbox or Google Drive), continues with the installed packages when there is no internet, and opens the browser instead of starting a second server when one is already running on the port. The two launcher scripts are UTF-8 **with a BOM** (Windows PowerShell 5.1 garbles their Ukrainian text otherwise); keep them that way.

## Backups

- **Automatic:** when the server starts (at most once per 10 minutes; the launcher makes it before `migrate`) and every time a session is closed. Files go to `<data folder>/backups/kt-YYYYMMDD-HHMMSS-<start|close|manual|restore>.sqlite3`; the newest 20 are kept. They are made with SQLite's online backup API, so they are safe while students are working.
- **By hand:** `/manage/backups/` (make one, download any) or `python -m uv run manage.py backup`.
- **Restore** (server stopped): `python -m uv run manage.py restore --list`, then `manage.py restore <file name or path>`. The current database is backed up first (`...-restore.sqlite3`), so a restore can be undone. Run `migrate` afterwards.
- There is no media yet (question images are not implemented), so the database file is everything. The code is `apps/core/backup.py`.

## Opening it from phones

1. Put the host and phones on the same network (a portable Wi-Fi router without internet is the most reliable; phone hotspots often cap at about 10 clients; school Wi-Fi often has client isolation, which blocks device-to-device traffic).
2. Set the Windows network profile to **Private**.
3. Allow the port once, in PowerShell as administrator:
   `New-NetFirewallRule -DisplayName "Knowledge Tester" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Private`
4. Disable sleep during the lesson and keep the laptop on mains power.
5. Scan the QR code from the terminal (or from a session's share screen), or type the URL.

## Settings

| What | How | Default |
|---|---|---|
| Data folder (database, media, `kt.toml`) | `KT_DATA_DIR` | `%LOCALAPPDATA%\KnowledgeTester` (Windows), `~/.local/share/knowledge-tester` (others) |
| Secret key | `KT_SECRET_KEY`, or `secret_key` in `<data folder>/kt.toml` | generated on the first start and written to `kt.toml` |
| Settings module | `DJANGO_SETTINGS_MODULE` | `config.settings.dev` (`manage.py serve` uses `lan`) |
| Port, host, threads | `manage.py serve --port 8000 --host 0.0.0.0 --threads 8` | 8000, all interfaces, 8 |

`ALLOWED_HOSTS` is still `*` (planned: derived from the LAN addresses, KT-005). Logging in is throttled per client address (10 wrong passwords per 5 minutes), registration with an invite code likewise.

## Checks and tests

```powershell
scripts\check.ps1                            # ruff check, ruff format --check, pytest
python -m uv run pytest apps/core apps/accounts tests
```

The full suite (about 1,640 tests) takes about a minute. pytest uses `config.settings.test`, which sets English as the default language so that older tests can assert English text, and a cheap password hasher (real PBKDF2 made the suite take 25+ minutes). Keep the `xlsx` extra installed (`uv sync --extra xlsx`; a bare `uv sync` removes it) or the XLSX import tests fail. The application itself (`dev`, `lan`) defaults to Ukrainian. Tests of Ukrainian behaviour select it explicitly (see `apps/core/tests/test_i18n.py`).

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

## People, classes and the admin area

- **Admin area (`/manage/`, admins only; teachers get 404):** teacher accounts (create, edit, deactivate, reset the password: typed or generated, a generated one is shown exactly once), and system settings (school name, optional teacher self-registration at `/accounts/register/` with an invite code; off by default). There is no e-mail on a LAN, so password resets are done by the admin.
- **Ownership:** a teacher sees only their own tests, sessions, groups and students; an admin sees everything. A foreign id always returns 404. Use `apps/people/access.py` (`groups_for`, `students_for`, `get_group_or_404`, `get_student_or_404`) for people data and `apps.delivery.services.can_manage` for sessions.
- **Roster (`/teach/people/`):** groups and students; each student can have a PIN (4 digits, plain text on purpose: a classroom convenience, not a credential) and a printable PIN sheet per group. Import a class from a pasted list (`Name` or `Name; Group`, numbering is stripped), a CSV (`,` `;` or tab; utf-8 or cp1251) or an XLSX. All routes end in the same preview with duplicate detection, then a confirm step.
- **Group sessions:** when a session is opened for a group, takers choose their name from the class list (names only) and, if "ask for a personal PIN" is on, type their PIN (5 wrong tries per student per 5 minutes). The attempt is linked to the student automatically. Anyone who has the session link can see the class list, so share it only with the class.
- **Free-name sessions:** afterwards, "Link to students" on the session page suggests matches (same name, same words in another order, fuzzy) for the teacher to confirm.
- **Student profile and gradebook:** the profile lists a student's linked attempts, averages per test project, notes, and CSV/PDF downloads; deleting a student either keeps their results (unlinked) or deletes them. The group gradebook is a students-by-sessions matrix of each student's best attempt, with CSV. A grade is marked provisional while any open answer behind it still waits for review.

## Daily use: navigation and safeguards

- **Navigation:** Tests · Sessions · People (· Manage for admins). Importing a test is a button on the Tests page and the dashboard. "Open session" sits next to every published test, on the dashboard, the tests list and the group page; it goes through a chooser (`/teach/sessions/new/`, `?group=<id>` pre-selects a class).
- **The student's page:** Submit sits at the end of the questions (the bottom bar holds the answered count, the save status and the timer; Enter in a field never submits). A row of small numbered buttons jumps to any question and shows which are answered. "One question per page" in the test settings shows one question at a time with Previous / Next (`static/js/questions.js`; without JavaScript every question shows). Once the attempt exists, a line at the top says who is answering.
- **Submitting with unanswered questions** asks once, right above Submit ("Submit anyway"): in the page with JavaScript, on the server without it; the timer's automatic submit never asks. A student's page also shows the save status, an offline strip and a warning one minute before time runs out.
- **Leaving the test page** (another tab or app, the phone locked, a notification opened) is counted with the time away (`static/js/away.js` -> `taker:away` -> `Attempt.away_count` / `away_seconds`). The student is told it is recorded; the teacher sees it on the session page, the attempt sheet, the results table and in the CSV. It is reported by the student's browser, so treat it as a hint, not proof.
- **Shared devices:** the done page offers "Another student on this device" (`taker:another`), which forgets the browser's finished attempt so the next student can start; the per-name and per-student attempt limits still apply.
- **Hand-in notes:** the session page and presentation mode pop up the name of every student who hands in, for 5 seconds (at most three at once).
- **Cancel an attempt** (attempt sheet, "Cancel attempt"): the attempt no longer counts in results, the gradebook or the profile, and the student can take the test again while the session is open. It cannot be undone.
- **Closing a session** asks first when somebody is still working; their answers so far are submitted automatically. A closed session can be reopened.
- **Adding time:** on the session page, "+5 / +10 / +15 min" extends the deadline of everyone who is still working (students who start later get the full time anyway). The student's page asks the server for the time left every 30 seconds and once more before the automatic submit (`static/js/timer.js`, an autosave request without answers), so the countdown follows; the same poll moves a student to the result page when the session was closed.
- **Variants:** a test can hold several parallel versions (`test.variants` in the file, or "Add a variant" on the test page, which copies the questions to be changed). Every taker gets one, handed out in turn from a random start, so the class is split evenly; the taker sees the variant's name, and results, sheets and the CSV say who had which. Format: [docs/exchange-format.md](docs/exchange-format.md).
- **Help page (`/teach/help/`, in the menu):** the prompt that turns a PDF textbook into an importable test, with a Copy button, plus the follow-up requests. The text is cut out of `docs/llm/test-from-textbook.uk.prompt.md` at run time (`apps/core/prompts.py`), so there is one source.
- **Review:** one Save for the whole sheet, or "Save and go to the next unreviewed attempt". The arrows at the top of a sheet (and the keyboard's left and right arrow keys) step through the results in the order of the results table, keeping its filter and sort; unsaved points ask before leaving.
- **New tests** start with a 30-minute time limit (`editing.NEW_TEST_TIME_LIMIT`); imported tests keep what their file says.

## Load test

`scripts/load_test.py` (standard library only) simulates a class taking one open session on a running server, optionally with a teacher polling the live stats. Run it against scratch data, never your real data folder; the usage is in the file's docstring. Measured: 32 simultaneous students without errors (slowest request 0.26 s), 100 without errors (slowest 3 s).

## PDF sheets

`apps/reports/pdf.py` builds PDFs with fpdf2 and the bundled DejaVu Sans (Latin and Cyrillic, embedded as a subset; licence in `assets/fonts/LICENSE_DEJAVU`). A sheet is one attempt: taker details, score and grade, then the questions with points and a result word. Options: compact or full (every option marked), A4 or Letter, show correct answers / comments / unanswered questions, shorten long questions, and for a whole session "continuous" (no page break between sheets). Entry points are `reports:attempt_pdf` and `reports:session_pdf` (`?status=` picks finished, needs_review or all). The labels follow the UI language of whoever downloads it. Tests read the text back with `pypdf` (a dev dependency).

**Paper test** (`apps/reports/paper_pdf.py`, `assessments:paper_pdf`, "Print for a written test" on the test page): the test as it is in the editor, printed for a written test. Every copy has blanks for the taker fields and the date, the questions in their own order with points, circles (one answer) or squares (several) before lettered options, one line for a short answer and ruled lines for an open one; a question is never split across pages. Options: one variant or all, 1 to 40 copies of each (every copy starts a new page and has its own page numbers), A4 or Letter, and an answer key on separate pages at the end. The labels follow the test's language (uk or en), since students read it.

## Layout

```
config/            Django project (settings: base, dev, lan)
apps/core/         landing, dashboard, healthz, `serve` command, LAN/IP helpers
apps/accounts/     custom User (admin/teacher roles), login, /manage/ admin area, registration
apps/assessments/  projects and tests (Test Document JSON), publishing
apps/exchange/     JSON import/export and validation; variants.py = helpers for tests with variants
apps/delivery/     sessions, share/QR screen, taker flow, group name picker, linking
apps/people/       groups, students, roster import, profile, gradebook, ownership helpers
apps/grading/      pure scoring engine and grade scales
apps/reports/      results, review of open answers, CSV
templates/         shared templates (base.html is the UI kit shell)
static/css/        base.css = UI kit (tokens, components, dark mode)
scripts/           check.ps1, start.ps1 (the launcher behind Start.cmd), allow-phones.ps1, i18n.py (translation catalog tooling)
docs/              quick-start.uk.md (teacher guide), exchange-format.md, llm/ (prompts), examples/
locale/            uk/LC_MESSAGES/django.po + django.mo
assets/fonts/      DejaVu Sans (regular, bold) + licence, embedded in PDF sheets
tests/             cross-app tests (smoke, offline guard)
idea/              plan, ADRs, issues, board
```

## Conventions

- UI rules (plan section 17): system fonts, one accent colour, no gradients or shadows, radius at most 6px, no emoji, tap targets of 44px, inputs of 16px or more. The CSS vocabulary is documented in the contracts file.
- No inline styles or scripts (CSP). Wrap user-visible strings for translation (see Translations).
- Code that works for **one attempt** (taking, grading, sheets) reads `attempt.test`, which is the test with the plain `questions` of that taker's variant; never `sitting.revision.test["questions"]`, which does not exist for a test with variants. Code for a whole test or session uses `apps.exchange.variants` (`all_questions`, `view`, `question_count`, `label`).
- Every teacher view needs `@login_required` and an ownership check (404 for foreign ids). Pages under `/manage/` use `apps.accounts.permissions.admin_required`.
- Run `scripts\check.ps1` before committing.
