# Development log

Newest entry first. Keep each entry short: what changed, what was learned, what comes next.

---

## 2026-11-11: Browser editor for tests

- Teachers can now build a test without writing JSON: "New test" (title + project), test settings (time limit, attempts, shuffling, what the student sees, grading scale and pass mark, taker fields), and a question editor for all five types, with up/down, duplicate and delete (with a confirmation page). Plain server-rendered forms, no JavaScript, so it works on a phone and under the CSP. Code: `apps/assessments/editing.py` (pure functions), `editor_views.py`, `templates/assessments/editor/`.
- Rule: every single question and the settings are validated by the importer before being stored, so an edit that would make the test invalid is refused with a plain message and the input is kept. Only the test as a whole may be incomplete (a new test has no questions and cannot be published until it has one).
- Editing a published test keeps its revisions untouched and marks "unpublished changes"; republishing creates the next revision.
- Option rows: clear the text to remove one, "Add an option" re-renders with one more row. Option and question ids are kept on edit.
- 92 new Ukrainian strings (`locale/uk/parts/editor.po` merged into the catalog). 413 tests.
- Not done yet: preview as taker (KT-206), test duplicate/delete/move between projects and project management (KT-201/204), question images (KT-207), "ready to publish" checklist on the editor (KT-205; the detail page already lists importer errors), custom grade thresholds in the UI.
- Next: preview as taker, PDF sheets, then Phase 6 (people).

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
