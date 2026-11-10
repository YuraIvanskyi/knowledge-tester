# Development log

Newest entry first. Keep each entry short: what changed, what was learned, what comes next.

---

## 2026-11-10: Planning groundwork

- Turned [concept.md](concept.md) into [plan.md](plan.md), covering the stack, architecture, data model, grading rules, exchange format, the LAN delivery design, UI guidelines and a roadmap of 10 phases (78 tasks).
- Recommended stack: Django 6 + HTMX + SQLite (WAL) + Waitress + WhiteNoise, fpdf2 for PDFs, segno for QR codes, pydantic for the exchange schema, and an optional LLM through an OpenAI-compatible API (Ollama by default).
- Set up tracking: [BOARD.md](BOARD.md), [issues/](issues/) with issue files for the Phase 0 tasks, [decisions/](decisions/) with ADR-0001 to ADR-0006 (proposed), and [specs/](specs/).
- Noted for setup: the repository sits in OneDrive, so the database and virtual environment must live outside it (plan §19.3).
- **Next:** review the open questions (plan §23, especially Q1 on question types), accept the ADRs, then start KT-001.
