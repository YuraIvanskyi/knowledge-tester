# Development log

Newest entry first. Keep each entry short: what changed, what was learned, what comes next.

---

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
