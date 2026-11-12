# Phase 6 (People): shared contracts

Goal: **a teacher runs a session for a class roster, and every attempt lands on the right student's profile** (plan §14, §21.8). Read [../plan.md §14](../plan.md#14-people-teachers-students-groups) first, and [prototype-contracts.md](prototype-contracts.md) for the rules that still apply (UI vocabulary, CSP, offline, i18n, ownership). This file only adds what is new.

Scope: KT-601 to KT-606. Not in scope: KT-607 sharing between teachers and KT-608 student logins (Could; plan Q3 = no student logins in v1), the local LLM (Phase 7), the final Ukrainian pass (Phase 8, but every new string is still wrapped now).

## Running things (Windows, from the repo root, bash tool)

```bash
export UV_PROJECT_ENVIRONMENT="$LOCALAPPDATA/KnowledgeTester/venv"
python -m uv run pytest apps/<your app> tests/test_offline_<you>.py     # your own tests (full suite takes ~80 s)
python -m uv run ruff check . && python -m uv run ruff format .
python -m uv run manage.py check
```

**Windows gotcha:** Python's `Path.read_text()` / `write_text()` / `open()` default to cp1252 here and silently corrupt UTF-8 (Cyrillic, `§`). Always pass `encoding="utf-8"`. Prefer the Edit/Write tools for source files.

## Already built (the frozen skeleton, committed)

- `apps/people/` app: `models.py` (`Group`, `Student`), `names.py` (`normalize_name`, `name_tokens`, `same_person_key`), `access.py` (ownership helpers), `urls*.py` (stubs), tests in `apps/people/tests/test_foundation.py`.
- `delivery.Attempt.student` (FK to `people.Student`, null, SET_NULL), `delivery.Sitting.group` (FK to `people.Group`, null, SET_NULL), `delivery.Sitting.use_pin` (bool).
- `accounts.SystemSettings` (singleton, `SystemSettings.load()`): `school_name`, `allow_registration`, `registration_code`.
- URL names below all resolve right now; unbuilt ones point at `apps.core.stubs.not_implemented` (HTTP 501). Replace the stub in **your own** urls module with the real view.
- Nav bar in `templates/base.html` already has People (`people:groups`) and, for admins, Manage (`manage:home`).

## Frozen (do not edit; if you truly need a change, work around it and say so in the final report)

`config/**`, every `models.py`, every `migrations/`, `pyproject.toml`, `apps/core/**`, `apps/people/models.py`, `names.py`, `access.py`, `urls.py`, `templates/base.html`, `static/css/base.css`, `tests/test_offline.py`, `tests/test_smoke.py`, `conftest.py`, `scripts/**`, `locale/uk/LC_MESSAGES/**`, `README.md`, `idea/**`.

The orchestrator commits, updates README/BOARD/log and compiles translations. **Do not run `git add` / `git commit` / `git stash` / `git checkout`.** Other workstreams are editing the same working tree at the same time: if an unrelated test fails because of someone else's half-finished work, ignore it and re-run later; never "fix" files you do not own.

## Ownership (edit only your own paths; everything else is read-only for you)

| WS | Task | Owns |
|---|---|---|
| **A** | KT-601 admin area | `apps/accounts/**` except `models.py`/`migrations`; `templates/manage/**`, `templates/registration/**`; `static/css/manage.css`; `locale/uk/parts/manage_area.po`; `tests/test_offline_manage.py` |
| **B** | KT-602 roster CRUD + import | `apps/people/urls_roster.py`, `views_roster.py`, `forms.py`, `services.py`, `importing.py`, `apps/people/tests/test_roster_*.py`; `templates/people/roster/**`; `static/css/people.css`; `locale/uk/parts/roster.po`; `tests/test_offline_roster.py` |
| **C** | KT-603 group sessions, KT-604 linking | `apps/delivery/**` except `models.py`/`migrations`; `templates/delivery/**`; `static/css/delivery.css`, `static/js/**`; **one line** in `templates/reports/session.html` (link to `delivery:link`); `locale/uk/parts/linking.po`; `tests/test_offline_linking.py` |
| **D** | KT-605 student profile | `apps/people/urls_profile.py`, `views_profile.py`, `profile.py`, `apps/people/tests/test_profile_*.py`; `apps/reports/student_pdf.py` (new file) + `apps/reports/tests/test_student_pdf.py`; `templates/people/profile/**`; `static/css/profile.css`; `locale/uk/parts/profile.po`; `tests/test_offline_profile.py` |
| **E** | KT-606 gradebook | `apps/people/urls_gradebook.py`, `views_gradebook.py`, `gradebook.py`, `apps/people/tests/test_gradebook_*.py`; `templates/people/gradebook/**`; `static/css/gradebook.css`; `locale/uk/parts/gradebook.po`; `tests/test_offline_gradebook.py` |

Every workstream puts its tests in its own files (add `__init__.py` where a new test package is needed). A page-level offline/CSP test goes in your own `tests/test_offline_<name>.py` (copy the idea from `tests/test_offline.py`; you may `from tests.test_offline import csp_violations, external_urls`).

## URL names (fixed; reverse them with these names)

| Name | Path | Owner | Notes |
|---|---|---|---|
| `manage:home` | `/manage/` | A | admin only (teachers get 404): links to teachers and settings |
| `manage:teachers` | `/manage/teachers/` | A | list: name, username, role, active, last login |
| `manage:teacher_create` | `/manage/teachers/new/` | A | |
| `manage:teacher_edit` | `/manage/teachers/<pk>/` | A | display name, role, active |
| `manage:teacher_password` | `/manage/teachers/<pk>/password/` | A | admin sets or generates a password (shown once) |
| `manage:teacher_active` | `/manage/teachers/<pk>/active/` | A | POST: activate/deactivate (never yourself, never the last active admin) |
| `manage:settings` | `/manage/settings/` | A | `SystemSettings` form |
| `accounts:register` | `/accounts/register/` | A | public; 404 unless `allow_registration`; needs `registration_code` |
| `people:groups` | `/teach/people/` | B | my groups (with student counts) + ungrouped students link |
| `people:group_create` / `people:group` / `people:group_edit` / `people:group_delete` | `/teach/people/groups/new/`, `.../groups/<pk>/` (+ `edit/`, `delete/`) | B | group page = student table with PIN column, add/import buttons, links to gradebook and a "Start a session" hint; delete asks: keep students ungrouped or delete them too |
| `people:group_pins` | `/teach/people/groups/<pk>/pins/` | B | POST: generate PINs for students without one (or regenerate all); GET: printable PIN list |
| `people:students` | `/teach/people/students/` | B | all my students, search + group filter |
| `people:student_create` / `people:student_edit` | `/teach/people/students/new/` (`?group=<pk>`), `.../students/<pk>/edit/` | B | |
| `people:import` / `people:import_confirm` | `/teach/people/import/`, `.../import/confirm/` | B | paste or CSV/XLSX upload -> preview with duplicate detection -> confirm |
| `people:student` | `/teach/people/students/<pk>/` | D | the profile page |
| `people:student_notes` | `.../students/<pk>/notes/` | D | POST: save notes |
| `people:student_delete` | `.../students/<pk>/delete/` | D | confirm page: **unlink** the attempts (keep results) or **delete** them too |
| `people:student_csv`, `people:student_pdf` | `.../students/<pk>/csv/`, `.../pdf/` | D | summary downloads |
| `people:gradebook`, `people:gradebook_csv` | `/teach/people/groups/<pk>/gradebook/`, `.../csv/` | E | |
| `delivery:link` | `/teach/sessions/<pk>/link/` | C | GET: suggestions table; POST: apply confirmed links |
| `delivery:create` | (existing) | C | gains: group dropdown (own groups) + "ask for personal PIN" checkbox |
| `taker:session` | (existing) | C | group-bound sessions show the name picker |

**Cross-links between workstreams:** a template may link to another workstream's URL name freely (all names resolve from the start). Do not rely on the *content* of another workstream's page in your tests.

## Data rules

- **Ownership:** a teacher sees and changes only their own groups, students, sessions and attempts; an admin sees all. Use `apps.people.access` (`groups_for`, `students_for`, `get_group_or_404`, `get_student_or_404`, `can_manage_*`) for people data and `apps.delivery.services.can_manage` for sessions. A foreign pk returns **404**, never 403/500, never leaks a name.
- **Group <-> student:** a student has at most one group, and `student.owner == group.owner` must hold (services enforce it; views never accept an arbitrary owner or foreign group id).
- **Duplicate detection:** two students of the same owner are duplicates when their `name_key` matches **or** `same_person_key` matches (word order swapped). Within a group this is a warning that needs an explicit "add anyway"; the import preview marks each row *new* / *duplicate of X* / *invalid*.
- **Attempt <-> student:** `Attempt.student` is the only link. `Attempt.taker` (what was typed) is never rewritten, so history stays honest. An attempt may only be linked to a student of the **same owner as the session** (`sitting.created_by`) (admins may link across).
- **Results that count for a student:** attempts with `status` in `submitted`/`auto_submitted` and `score is not None`; `voided` never counts; `pending_reviews > 0` means the grade is **provisional** (show it as such wherever a number or grade appears). Percent = `Attempt.percent`.
- **Group-bound sessions (C):** `sitting.group` set -> the taker page replaces the free "name" field by a searchable list of that group's **active** students (names only, never PINs or notes). If `sitting.use_pin`, the taker also types the student's `pin`; a wrong PIN is refused with a plain message and throttled (a few tries per student per few minutes; keep it simple). A student with no PIN set cannot be picked in a PIN session. The attempt gets `student=<picked>` and `taker["name"] = student.full_name`; the other `taker_fields` are still asked. `max_attempts` is enforced per student (not only per typed name). The group's class list is visible to anyone who has the session link: acceptable, but document it in the code comment, and never show the list for a closed session.
- **Linking after the fact (C, KT-604):** `delivery:link` lists the session's finished-or-not, not voided attempts that have no student, each with ranked suggestions among the **teacher's active students** (exact `name_key`, same words in other order, then fuzzy `difflib` on `same_person_key`; score threshold, top 3). The teacher confirms per row with a select (suggestion pre-selected only for exact/word-order matches) and applies all at once. Already-linked attempts can be re-pointed or unlinked. The page is useful for group-bound sessions too (shows all linked). Name-matching helpers live in `apps/delivery/linking.py` and use `apps.people.names`.
- **Student profile (D):** header (name, group, PIN visible to the owner, active flag), notes form, history table of linked attempts (test, session, date, score, percent, grade, provisional marker; each row links to `reports:attempt`), averages per project (mean of percent over counted attempts, plus count), overall average, CSV and PDF summary. Delete flow as in the URL table.
- **Gradebook (E):** rows = the group's students (active first, then inactive that have results), columns = sessions that are bound to the group **or** have attempts linked to the group's students (oldest first), cell = percent of the student's **best** counted attempt in that session (state this rule on the page), `—` if none; provisional cells are marked; last column = student average, last row = session average; CSV export of the same matrix (UTF-8 with BOM, `;`-safe quoting via `csv`, formula-injection safe: cells starting with `= + - @` are prefixed with `'`). Cell links to the attempt sheet.
- **CSV safety (everyone who exports):** prefix cells beginning with `=`, `+`, `-`, `@` (or tab/CR) with `'`.

## Admin area rules (A)

- Admin-only guard: write a reusable decorator in `apps/accounts/permissions.py` (`admin_required`: anonymous -> login redirect, non-admin -> **404**). Everything under `/manage/` uses it.
- Teachers are created with username + display name + role + initial password (validated with Django's password validators). Resetting a password sets a new one (typed or generated, **shown once** on the next page, never stored in plain text). Deactivate never deletes data; an inactive teacher cannot log in (Django does this) and their sessions keep working for students.
- Safety: an admin cannot deactivate or demote themselves, nor remove the last active admin.
- `accounts:register`: only when `SystemSettings.allow_registration`; the invite code must match (`registration_code`, constant-time compare), creates a **teacher**, logs them in. The login page shows a "Register" link only when enabled. Basic throttling on wrong invite codes is nice, not required.
- `school_name` is stored only (printing it in PDFs is a later task).

## UI / tests / i18n / verification

- UI vocabulary and CSP rules: see [prototype-contracts.md](prototype-contracts.md#ui--css-vocabulary-d-defines-it-in-staticcssbasecss-everyone-uses-it). Tables must reflow below 640 px (`.table` + `data-label`), 360 px wide first, tap targets >= 44 px, inputs >= 16 px. No JavaScript is required for any teacher page (small optional enhancements in `static/js/<name>.js` are fine). New CSS goes in **your own** css file, loaded via `{% block head %}`.
- i18n: wrap every user-visible string (templates, forms, messages, CSV/PDF headers). Counts use `ngettext` / `{% blocktranslate count %}`. **Write the Ukrainian translations yourself** into your fragment `locale/uk/parts/<name>.po` (header like `locale/uk/parts/manage.po`: 3 plural forms; every `msgid` exactly as in the code; `msgstr[0..2]` for plurals). Do **not** edit `locale/uk/LC_MESSAGES/django.po` and do not run `scripts/i18n.py` (the orchestrator extracts, merges and compiles at the end). Tests run in English.
- Tests: pytest for logic and views (permissions, 404 on foreign ids, CSRF/POST-only actions, edge cases, Ukrainian names with apostrophes/hyphens). Target: thorough but fast. `ruff check .` and `ruff format .` must pass.
- **Self-verification is mandatory, not optional.** Besides pytest, boot your part for real and use it like a user:
  1. `export KT_DATA_DIR="<scratchpad>/ws-<letter>"` (own folder; never use the default data folder), `python -m uv run manage.py migrate`, create users / data through a small script or `seed_demo`, then `python -m uv run manage.py runserver 127.0.0.1:<port> --noreload` in the background (ports: A 8101, B 8102, C 8103, D 8104, E 8105). **Stop it when you are done.**
  2. Drive it with a script (`urllib` + `http.cookiejar`, handle the CSRF token): log in, walk your flows end to end, check status codes and the key content, including a second teacher who must get 404s.
  3. Look at your pages once: save the HTML you fetched to a scratch file with the CSS inlined, render at phone width with `"/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" --headless --screenshot=<png> --window-size=390,900 file:///<html>` and view the PNG with the Read tool. Fix anything ugly or overflowing.
- Final report (your last message): what you built (files), URL names you implemented, decisions you made where this contract was silent, anything you could not do or had to work around, and what you verified live. Keep it under 40 lines.
