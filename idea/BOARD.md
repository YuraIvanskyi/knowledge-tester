# Project Board

This board is the single source of truth for status. The task content lives in [plan.md §21](plan.md#21-roadmap), and detail lives in [issues/](issues/).

**Last updated:** 2026-11-10 · **Current phase:** 0 (Foundation) · **Next milestone:** M1, first classroom run (end of Phase 4)

**Legend:** `[ ]` open · `[~]` in progress · `[x]` done · `[!]` blocked · Size **S** ≤ ½ day · **M** 1–2 days · **L** 3+ days · *(should)* / *(could)* = priority below Must

---

## Overview

| Phase | Goal | Status | Done |
|---|---|---|---|
| 0. Foundation | A running skeleton that a phone can reach over the LAN | Ready | 0 / 9 |
| 1. Domain core and exchange format | Test data model and JSON import/export | Backlog | 0 / 8 |
| 2. Authoring UI | Build and edit tests in the browser | Backlog | 0 / 7 |
| 3. Delivery | Sessions, links and QR, taking tests on phones | Backlog | 0 / 10 |
| 4. Grading and results | Autograding, review queue, results | Backlog | 0 / 8 |
| 5. Print and export | PDF sheets, CSV/XLSX/JSON results | Backlog | 0 / 6 |
| 6. People | Teacher admin, students, groups, profiles | Backlog | 0 / 8 |
| 7. Local LLM assistant | Imports and drafting with a local LLM | Backlog | 0 / 9 |
| 8. Ukrainian | Full Ukrainian localization | Backlog | 0 / 4 |
| 9. Hardening and packaging | Backups, launcher, security, docs | Backlog | 0 / 9 |
| **Total** | | | **0 / 78** |

## Milestones

| Milestone | Reached when | Status |
|---|---|---|
| M1: first classroom run | Phases 0–4 are done, and a real class takes a test over the LAN with automatic scores | Not started |
| M2: MVP complete | Phase 5 is done, and PDF sheets print | Not started |
| M3: class records | Phase 6 is done | Not started |
| M4: assistant | Phase 7 is done | Not started |
| M5: Ukrainian | Phase 8 is done | Not started |
| v1.0 | Phase 9 is done | Not started |

---

## In progress

_Nothing yet._

## Ready (listed in suggested order)

- [ ] [KT-001](issues/KT-001-repo-tooling-bootstrap.md) Repository and tooling bootstrap · S
- [ ] [KT-002](issues/KT-002-django-skeleton.md) Django project skeleton and app layout · M
- [ ] [KT-004](issues/KT-004-data-dir-sqlite.md) Data folder and SQLite configuration · S
- [ ] [KT-003](issues/KT-003-user-model-auth.md) Custom User model, roles and auth (before the first migrate) · M
- [ ] [KT-008](issues/KT-008-test-harness.md) Test harness and quality gates · S
- [ ] [KT-006](issues/KT-006-base-ui-kit.md) Base UI kit · M
- [ ] [KT-007](issues/KT-007-i18n-plumbing.md) i18n plumbing · S
- [ ] [KT-005](issues/KT-005-lan-serve-command.md) LAN `serve` command · M
- [ ] [KT-009](issues/KT-009-developer-readme.md) Developer README and first-run docs · S

## Needs decision

Each of these has a default assumption, so none of them blocks work. Details are in [plan.md §23](plan.md#23-open-questions).

- [ ] Q1: meaning of the single-correct, few-correct and multiple-choice task types (blocks the final shape of KT-102 and KT-401)
- [ ] Q2: default grade scale
- [ ] Q3: student logins
- [ ] Q4: host operating system
- [ ] Q5: maximum number of concurrent takers
- [ ] Q6: images and formulas in questions
- [ ] Q7: several teachers on one host
- [ ] Q8: hardware for the local LLM
- [ ] Q9: showing correct answers after submit

## Blocked

_Nothing yet._

---

## Backlog

### Phase 1: Domain core and exchange format
- [ ] KT-101 Models: Project, Assessment, Question, Option, Revision · M
- [ ] KT-102 Test Document v1 pydantic models and semantic validators · M
- [ ] KT-103 Validation report: paths, plain messages, hints · S
- [ ] KT-104 Serializers DB ⇄ Test Document, with round-trip tests · M
- [ ] KT-105 `export_schema`, exchange-format doc, examples · S
- [ ] KT-106 Import UI, preview and `import_test` command · M
- [ ] KT-107 Export of a test as JSON and of a project bundle · S
- [ ] KT-108 LLM prompt pack for creating tests · S

### Phase 2: Authoring UI
- [ ] KT-201 Teacher dashboard and projects · M
- [ ] KT-202 Test settings form · M
- [ ] KT-203 Question editor, all v1 types (HTMX) · L
- [ ] KT-204 Reorder, duplicate, move · M
- [ ] KT-205 Editor validation and "ready to publish" checklist · S
- [ ] KT-206 Preview as taker · S
- [ ] KT-207 Question images *(should)* · M

### Phase 3: Delivery
- [ ] KT-301 Publish → Revision · M
- [ ] KT-302 Sessions: create, open, close, codes · M
- [ ] KT-303 Share screen: QR, URL selection, presentation mode · M
- [ ] KT-304 Taker entry: code landing page, identity fields · M
- [ ] KT-305 Taker question flow (works without JS) · L
- [ ] KT-306 Resilience: resume, autosave, idempotent submit, close finalization · M
- [ ] KT-307 Timer: server deadline, auto-submit, extend · M
- [ ] KT-308 Seeded shuffling · S
- [ ] KT-309 Teacher live monitor · S
- [ ] KT-310 Load-test script and first measurement · S

### Phase 4: Grading and results
- [ ] KT-401 Scoring engine, all types and modes (can start after Phase 1) · M
- [ ] KT-402 Text normalization utilities · S
- [ ] KT-403 Grade scales and provisional flag · S
- [ ] KT-404 Grade on submit and regrading · M
- [ ] KT-405 Review queue · M
- [ ] KT-406 Results views · M
- [ ] KT-407 Taker result screen · S
- [ ] KT-408 Item analysis *(should)* · S

### Phase 5: Print and export
- [ ] KT-501 PDF foundation: fpdf2 and fonts · S
- [ ] KT-502 Attempt sheet PDF · M
- [ ] KT-503 Batch PDF · S
- [ ] KT-504 Print CSS · S
- [ ] KT-505 Results CSV, plus XLSX *(should)* · S
- [ ] KT-506 Results JSON v1 · S

### Phase 6: People
- [ ] KT-601 Admin area: teachers and system settings · M
- [ ] KT-602 Groups and students: CRUD and imports · M
- [ ] KT-603 Group-bound sessions with pick-your-name entry · M
- [ ] KT-604 Link attempts to students after the fact · S
- [ ] KT-605 Student profile · M
- [ ] KT-606 Group gradebook *(should)* · M
- [ ] KT-607 Ownership audit and teacher sharing *(could)* · S
- [ ] KT-608 Read-only student login *(could)* · M

### Phase 7: Local LLM assistant
- [ ] KT-701 LLM settings, client and feature flag · S
- [ ] KT-702 Job runner · M
- [ ] KT-703 Students from text · S
- [ ] KT-704 Students from an image · M
- [ ] KT-705 Students from a file · S
- [ ] KT-706 Draft, structure or fix a test · M
- [ ] KT-707 Editor helpers *(should)* · S
- [ ] KT-708 Open-answer grading suggestions *(should)* · S
- [ ] KT-709 Prompt files and evaluation fixtures · S

### Phase 8: Ukrainian
- [ ] KT-801 Ukrainian UI translation · M
- [ ] KT-802 Language switching · S
- [ ] KT-803 Locale formats and PDF labels · S
- [ ] KT-804 Ukrainian docs *(should)* · S

### Phase 9: Hardening and packaging
- [ ] KT-901 Backups and restore · M
- [ ] KT-902 One-click launcher and first-run setup · M
- [ ] KT-903 Network diagnostics page · S
- [ ] KT-904 Security review · M
- [ ] KT-905 Performance pass · M
- [ ] KT-906 Accessibility pass · S
- [ ] KT-907 Teacher quick-start guide · S
- [ ] KT-908 Release checklist and v1.0 · S
- [ ] KT-909 mDNS name and packaged Windows bundle *(could)* · M

### Unplanned / ideas
_New ideas go here first, then into the plan once they're accepted._

- Additional question types: true/false, matching, ordering, rating (plan §9.1)
- Math formulas (KaTeX, loaded only when a test uses it)
- Markdown subset in question text

---

## Done

- [x] KT-000 Planning groundwork: plan, board, ADRs, issue system · 2026-11-10
