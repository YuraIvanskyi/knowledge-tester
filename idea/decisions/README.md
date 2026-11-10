# Architecture Decision Records

An ADR records one significant choice: its context, the decision, its consequences and the alternatives considered. ADRs are never rewritten after acceptance. To change a decision, write a new ADR that supersedes the old one, and set the old one's status to `Superseded by ADR-nnnn`.

**Statuses:** `Proposed` → `Accepted` (or `Rejected`), and later `Superseded by …`.

The ADRs below are **Proposed** and are accepted when Phase 0 starts, unless the review changes them.

## Index

| ADR | Title | Status |
|---|---|---|
| [0001](0001-django-server-rendered-htmx.md) | Django, server-rendered pages and HTMX; no SPA and no build step | Proposed |
| [0002](0002-sqlite-wal-data-dir.md) | SQLite in WAL mode, in a data folder outside the repository and OneDrive | Proposed |
| [0003](0003-waitress-whitenoise-lan.md) | Waitress and WhiteNoise for LAN serving over plain HTTP | Proposed |
| [0004](0004-canonical-test-document.md) | One canonical Test Document (pydantic) and immutable revisions | Proposed |
| [0005](0005-pdf-fpdf2.md) | fpdf2 for PDF sheets | Proposed |
| [0006](0006-llm-openai-compatible-optional.md) | The LLM is optional and assistive, reached through an OpenAI-compatible API, with an in-process job worker | Proposed |

## Template

```markdown
# ADR-nnnn: Title

- **Status:** Proposed (YYYY-MM-DD)
- **Related:** plan.md §x, KT-xxx

## Context
What forces are at play? What problem needs deciding?

## Decision
What we will do.

## Consequences
What becomes easier, what becomes harder, what we commit to.

## Alternatives considered
- Option: why not.
```
