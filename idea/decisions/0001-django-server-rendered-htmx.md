# ADR-0001: Django, server-rendered pages and HTMX; no SPA and no build step

- **Status:** Proposed (2026-11-10)
- **Related:** plan.md §6, §17.6 · KT-002, KT-006

## Context

The app is mostly forms: authoring tests, taking tests, settings and rosters. It needs auth with roles, an admin, migrations, i18n with Ukrainian plurals, CSRF protection and file uploads. Takers use low-end phones on weak Wi-Fi, and the host is a teacher's Windows laptop with no internet. The project wants to stay lightweight and easy to run.

## Decision

- **Django 6.x** (the latest stable release at Phase 0, moving to 6.2 LTS when it ships) on **Python 3.13** (3.12 or later), managed with **uv**.
- **Server-rendered templates.** Interactivity comes from **HTMX 2** (vendored) and small vanilla JS modules. Django's built-in template partials serve HTMX fragments.
- **Hand-written CSS** with custom-property tokens. No CSS framework, no Node, no bundler.
- The taker flow must work **with JavaScript disabled**. JavaScript only adds autosave, the timer and live updates.

## Consequences

- **Easier:** most required features come built in. There's no build pipeline, and payloads are tiny (a taker page target of 60 KB or less). Development is pure Python, and the same stack serves Phase 7 (LLM and document processing).
- **Harder:** rich client interactions such as drag-and-drop editing need care. Up/down buttons are used on phones, with optional SortableJS on desktop. There's no offline-first PWA, because Service Workers need HTTPS anyway.
- **Commitment:** every UI string is translatable from day one, and every page is built for a 360 px-wide screen first.

## Alternatives considered

- **Flask or FastAPI with Jinja:** we'd rebuild auth, admin, forms, migrations and i18n ourselves.
- **An SPA (React, Vue, Svelte) with an API:** build tooling, heavier client JS, and two codebases. A poor fit for low-end phones.
- **PocketBase (Go, single binary):** easy to distribute, but it needs a separate SPA, and its i18n, PDF and LLM tooling is weaker. Revisit only if a single `.exe` becomes the top priority.
