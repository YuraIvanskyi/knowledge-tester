# Development log

Newest entry first. Keep each entry short: what changed, what was learned, what comes next.

---

## 2026-11-13: UX wave integration gate closed

- **The "hanging" full `pytest` was not a hang.** Nearly every test creates a user, and Django 6's default PBKDF2 hasher costs about a second per user here; the suite needed 25+ minutes (earlier runs took about 80 s on a faster setup). `config/settings/test.py` now uses the MD5 hasher: **1206 tests in 27 s**, ruff and `manage.py check` clean. No test depended on the hasher.
- **One real failure, environmental:** `test_bad_uploads_give_plain_messages` failed because the rebuilt venv had no openpyxl. A bare `uv sync` (used by `scripts/start.ps1`) removes the `xlsx` extra; `start.ps1` now syncs with `--extra xlsx`, and the README says so.
- **End-to-end pass done** (headless Edge against a scratch instance, 11 of 11 checks): dashboard -> create form -> class session -> a student submits half-empty and sees the unanswered step -> confirms -> teacher cancels the attempt -> the student sees the cancelled note and retakes -> another student keeps working -> closing asks first ("1 student still works") -> auto-submitted -> review with "Save and go to the next" returns to the results. The attempt that "stayed in progress" in workstream C's script was the new confirmation step (a first submit lands on `/submit/`; the attempt finishes after "Submit anyway"), not a bug.
- **Visual re-check** of Manage (teachers, new teacher, settings) at 390 and 1280 px: no overflow, nothing broken. Phone results page 1,859 px for 2 attempts, no sideways scroll.
- README: navigation, cancel attempt, close confirmation, review, test notes.
- **Still open:** tap targets of 21-24 px on inline table links and "Refresh" (UX-18, partly); Delete test / Export JSON to the page bottom on phones; the Phase 6 wave 2 items (ownership audit matrix, 32-taker load run, code review).
- **Next:** wave 2 of Phase 6 (ownership audit and load run), then Phase 7 or the Phase 3/4 gaps.

## 2026-11-13: UX review wave (UX-01 to UX-18), built; integration gate open

- **Method:** a UI/UX review driven through headless Edge over CDP at 390 and 1280 px (`scripts/ui_shots.mjs`), then a contracts doc ([specs/ux-review-contracts.md](specs/ux-review-contracts.md)), a frozen Wave 0 skeleton (commit c39a7bc) and five parallel workstreams with disjoint file ownership, committed one by one (D aff1c83, C 0abb19d, E 94d1783, B fc8d6a7, A 506bf7c).
- **Built:** confirm before submitting unanswered questions (server-side, the timer's auto-submit never asks); cancel an attempt, after which the student can retake; confirm before closing a session while students work; save status, offline strip and a one-minute timer warning; one-row bottom bar; one Save per review sheet with "save and go to the next"; session chooser (`delivery:pick`, `?group=`) and "Open session" on the test page, tests list, dashboard and group page; presentation mode for the share screen; phone card pattern (`cell-title`, `cell-actions`, `table-compact`) on the long tables; lean header (admin: two rows on a phone, one from 700 px).
- **Measured at 390 px (Ukrainian, demo data):** test page 4,088 -> 2,380 px; session results 4,906 -> 2,893 px; import preview (13 rows) 2,985 -> 1,741 px; share screen (8 takers) 2,100 -> 1,245 px; sessions list no longer scrolls sideways (425 -> 390 px); taker bottom bar about 105 -> 61 px; admin header 133 -> 90 px.
- **Learned:** `runserver --noreload` caches templates, so restart after template edits; Git Bash heredocs collapse the backslashes of JS regexes (write such scripts with the Write tool); headless Edge follows the system theme, which is dark here; a full-page capture draws sticky bars mid-page.
- **Open (stopped here on request):**
  1. The full `pytest` run did not finish (28 minutes against about 80 s; killed). Each workstream passed its own tests (`apps/delivery`, `apps/reports`, `apps/assessments apps/core`, `apps/people apps/accounts`, plus `tests/`). Find the hanging test with `pytest -v --timeout` or by running the apps one by one; suspects are the new submit-confirmation and close-confirmation paths and the `tests/test_offline_*` files. Wave 0 alone passed the full suite in the normal time.
  2. The end-to-end pass of section 10 of the contracts is not run. A script exists in the scratchpad (`e2e.mjs`), not in the repo; it covers dashboard -> chooser -> class session -> half-empty submit -> panel -> cancel -> retake -> close with one student working -> review with "save and next". One thing to confirm there: workstream C saw an attempt stay "in progress" after a scripted final submit; it is probably the new unanswered-questions step, unconfirmed.
  3. Visual re-check of the Manage settings and create/edit pages after the final CSS changes (E did not).
  4. README (navigation, cancel attempt, close confirmation) and the contracts doc status line.
- **Next:** unblock the full suite, run the end-to-end pass, fix what it finds, then update README.

## 2026-11-12: Phase 6, People (KT-601 to KT-606)

- **Method:** first a frozen skeleton (the `apps.people` models `Group` and `Student`, `Attempt.student`, `Sitting.group` and `use_pin`, `accounts.SystemSettings`, ownership helpers in `apps/people/access.py`, name normalisation in `names.py`, reserved URL names pointing at a 501 stub) and a contract ([specs/people-contracts.md](specs/people-contracts.md)); then five agents in parallel with disjoint file ownership, each verifying its part on a live server with its own data folder. Translations were written as fragments in `locale/uk/parts/` and merged once (735 catalog entries, `i18n.py check` clean).
- **Built:** admin area at `/manage/` (teacher list, create, edit, deactivate, password reset with a password shown once, system settings, invite-code self-registration that is off by default and throttled); roster (groups, students, printable PIN sheet, one preview-and-confirm import for pasted lists, CSV with encoding/delimiter detection and XLSX through the `xlsx` extra); group-bound sessions (name picker, optional PIN with 5 tries per student per 5 minutes, `max_attempts` per student on all three start paths); linking of free-name attempts with ranked suggestions; student profile (history, averages per project, notes, CSV, PDF, delete with a keep-or-delete choice); group gradebook with CSV.
- **Decisions:** a student belongs to at most one group; PINs are plain text on purpose (classroom convenience, not a credential); gradebook cell = best counted attempt; "counted" = submitted or auto-submitted, has a score, not voided, and "provisional" while `pending_reviews > 0` everywhere; KT-607 sharing between teachers and KT-608 student logins are skipped (Could; plan Q3).
- **Learned:** `button.btn` in `base.css` outranked `.btn-primary`, so primary buttons were unstyled and three workstreams each added a workaround (fixed once in `base.css`, workarounds removed); Python text IO defaults to cp1252 on this Windows machine, so a one-line edit corrupted UTF-8 files until `encoding="utf-8"` was added; headless Edge cannot render below about 500 px, so phone views are rendered in a 390 px iframe; SQLite orders "І" after "Я", so Ukrainian sorting is done in Python.
- **Known limits:** the class list of a group session is visible to anyone who has the session link (names only); a classmate can lock another student out of a PIN session for 5 minutes by guessing; PDF layout was checked as extracted text only; the school name from settings is stored but not printed yet.
- 1113 tests (was 454), ruff clean.
- **Wave 2 (running):** ownership audit matrix over every URL, a read-only code review of the seams between the workstreams, an end-to-end scenario plus a 32-taker load run on the real Waitress server, and a UX pass in Ukrainian, light and dark. Results go in the next entry.
- **Next:** finish wave 2, then Phase 7 (local LLM assistant) or the Phase 3/4 gaps the prototype skipped (resilience and timer details, item analysis).

## 2026-11-11: Fixes after first review

- **Language switcher:** now abbreviations (ENG, UA; the full name is the tooltip and the accessible name). The same markup (`templates/core/_lang_switch.html`) is rendered in the header and in the footer; CSS shows the header one from 640 px up and the footer one below that (no JS). The footer is hidden on desktop.
- **Delete:** a test (confirmation page says how many sessions and attempts go with it; `Sitting.revision` is PROTECT, so `services.delete_assessment` removes sessions first, in one transaction) and a session (all its attempts and answers; the test is untouched). Both are POST-after-confirmation and ownership-checked. Buttons on the test page, the session page and the session list.
- **Reopen:** a closed session can be reopened (`delivery:reopen`), same link and code, `closed_at` cleared. Attempts auto-submitted at close stay finished, and `max_attempts` still applies.
- 16 new Ukrainian strings, 454 tests.

## 2026-11-11: PDF sheets (KT-501 to KT-503)

- `apps/reports/pdf.py` (fpdf2 + bundled DejaVu Sans, extracted from the matplotlib wheel; licence kept in `assets/fonts/`). One sheet per attempt: header with taker fields, score, grade and a "provisional" note, then each question with points, a result word (colour plus text, so it survives black-and-white printing), the answer, the correct answer and the teacher comment. Questions are kept together on a page; page footer shows the attempt code, taker and page n/N.
- Options: compact or full, A4 or Letter, correct answers / comments / unanswered on or off, shorten long questions, and for batches "continuous". Batch = the whole session sorted by name, default finished attempts only (`status` filter: needs_review, all without voided).
- UI: a "Download PDF" box on the attempt sheet and "Download all as PDF" on the session results page. The PDF opens inline in the browser with a Unicode file name.
- Checked: Ukrainian glyph coverage of both fonts, text read back with pypdf, hostile input (control characters, emoji, very long words), sizes (about 24 KB for a sheet; 40 sheets under 1 MB), permissions. Looked at the rendered pages once.
- Learned: with a wider points column the question layout no longer leaves gaps; page numbers in a batch are for the whole file, not per sheet.
- Not done: selection of individual attempts by checkboxes (only the status filter), per-sheet page numbers in a batch, the language of a test driving the PDF labels (KT-803), a school name/logo in the header.
- Next: Phase 6 (people).

## 2026-11-11: Browser editor for tests

- Teachers can now build a test without writing JSON: "New test" (title + project), test settings (time limit, attempts, shuffling, what the student sees, grading scale and pass mark, taker fields), and a question editor for all five types, with up/down, duplicate and delete (with a confirmation page). Plain server-rendered forms, no JavaScript, so it works on a phone and under the CSP. Code: `apps/assessments/editing.py` (pure functions), `editor_views.py`, `templates/assessments/editor/`.
- Rule: every single question and the settings are validated by the importer before being stored, so an edit that would make the test invalid is refused with a plain message and the input is kept. Only the test as a whole may be incomplete (a new test has no questions and cannot be published until it has one).
- Editing a published test keeps its revisions untouched and marks "unpublished changes"; republishing creates the next revision.
- Option rows: clear the text to remove one, "Add an option" re-renders with one more row. Option and question ids are kept on edit.
- 92 new Ukrainian strings (`locale/uk/parts/editor.po` merged into the catalog). 413 tests.
- Preview as taker (KT-206): "Preview" on the test page renders the draft with the real taker template (`delivery.taker_views.render_preview`), so shuffling, hints, the choose-N cap and time-limit notice match what students see. Nothing is stored (no sitting/attempt); posting only re-renders with the answers kept, and `autosave.js` sends nothing in preview mode (`data-preview`). Correct answers and rubrics are never in the page.
- Not done yet: test duplicate/delete/move between projects and project management (KT-201/204), question images (KT-207), "ready to publish" checklist on the editor (KT-205; the detail page already lists importer errors), custom grade thresholds in the UI.
- Next: PDF sheets, then Phase 6 (people).

## 2026-11-11: Simplistic prototype (end-to-end)

- Built in parallel by four workstreams (see [specs/prototype-contracts.md](specs/prototype-contracts.md)): exchange + assessments, grading + reports, delivery (sessions, QR, taker flow), core + accounts + UI kit + `serve` + test harness.
- Verified on a live server with a script: login -> import/publish (`seed_demo`) -> open session -> QR/code -> student answers on the taker pages -> autograde (provisional while an open answer is pending) -> manual review -> final grade -> CSV -> close session. 349 tests pass, ruff clean.
- **Deviations from the plan, to revisit:** questions/options are not separate tables (the Test Document JSON is the source of truth, KT-101 is only partly done); no in-browser test editor (tests come from JSON import, KT-203 not started); no PDF sheets (browser print CSS only), no student/group roster, no LLM, no Ukrainian translation, no backups/launcher; ALLOWED_HOSTS is `*`; `one_question_per_page` ignored; no login throttling.
- Server caps `choose_n` selections at `n` (the scoring formula would otherwise reward ticking everything).
- Next: in-browser editor, PDF sheets, then Phase 6 (people).

## 2026-11-10: Planning groundwork

- Turned [concept.md](concept.md) into [plan.md](plan.md), covering the stack, architecture, data model, grading rules, exchange format, the LAN delivery design, UI guidelines and a roadmap of 10 phases (78 tasks).
- Recommended stack: Django 6 + HTMX + SQLite (WAL) + Waitress + WhiteNoise, fpdf2 for PDFs, segno for QR codes, pydantic for the exchange schema, and an optional LLM through an OpenAI-compatible API (Ollama by default).
- Set up tracking: [BOARD.md](BOARD.md), [issues/](issues/) with issue files for the Phase 0 tasks, [decisions/](decisions/) with ADR-0001 to ADR-0006 (proposed), and [specs/](specs/).
- Noted for setup: the repository sits in OneDrive, so the database and virtual environment must live outside it (plan §19.3).
- **Next:** review the open questions (plan §23, especially Q1 on question types), accept the ADRs, then start KT-001.
