# idea/: planning and tracking

Everything about *what* we're building, *why*, and *how far along* it is lives here. Application code never goes in this folder.

## Map

| Path | What it is | Who updates it, and when |
|---|---|---|
| [concept.md](concept.md) | The original idea, kept as written | Never edited. Reinterpretations go into the plan |
| [plan.md](plan.md) | The master plan: stack, architecture, feature designs, roadmap with task IDs | Whenever scope or design changes. Each change gets a line in §24 |
| [BOARD.md](BOARD.md) | Project board: phase progress, milestones, the Ready, In progress and Done columns | Every time a task changes status |
| [issues/](issues/) | One file per task or bug, holding acceptance criteria and working notes | When a task moves to Ready, and while it's being worked on |
| [decisions/](decisions/) | Architecture Decision Records (ADRs) | When a significant or hard-to-reverse choice is made or changed |
| [specs/](specs/) | Detailed specifications for complex features, written just before a phase starts | At the start of a phase that needs one |
| [log.md](log.md) | Dated development journal, newest entry first | At the end of each work session, or when something notable happens |

## Workflow for one task

1. **Pick** the top item from *Ready* on [BOARD.md](BOARD.md).
2. **Open its issue file.** If it doesn't exist yet, copy [issues/_template.md](issues/_template.md) and fill in the context and acceptance criteria from the plan.
3. **Start:** set `status: in-progress` in the issue's front matter and move the line to *In progress* on the board.
4. **Work:** add short dated notes to the issue's *Log* section, covering findings, deviations and follow-ups.
5. **Finish:** check the Definition of Done ([plan.md §20.2](plan.md#202-definition-of-done-every-issue)). Then set `status: done`, mark the item `[x]`, move it to *Done* with the date, update the phase's count in the Overview table, and add a [log.md](log.md) entry if it's notable.
6. **Decided something big?** Write an ADR. **Scope changed?** Update plan.md and its changelog.

When a phase is finished, check its exit criteria in plan.md §21, mark the phase done on the board, and create issue files for the next phase's tasks.

## Conventions

**IDs**

- `KT-<phase><nn>` for planned tasks: KT-001…KT-009 are Phase 0, KT-101… are Phase 1, and so on. An ID never changes, even if the task moves to another phase.
- `BUG-<nnn>` for bugs found along the way.
- `UX-<nn>` for the findings of the 2026-11-13 UI/UX review ([specs/ux-review-contracts.md](specs/ux-review-contracts.md)); they cut across phases, so they have their own series.
- `Q<n>` for open questions, tracked in [plan.md §23](plan.md#23-open-questions).
- `ADR-<nnnn>` for decisions.

**File names:** `KT-101-short-slug.md`, `BUG-001-short-slug.md`, `0007-short-slug.md`.

**Statuses** (in issue front matter): `backlog` → `ready` → `in-progress` → `review` → `done`, or `blocked` with a reason in the Log.

**Sizes:** S (half a day or less), M (1–2 days), L (3 or more days; split it if you can).

**Priorities:** `must`, `should`, `could`. Everything in Phases 0–5 marked `must` is the MVP.

**Dates:** ISO format, `YYYY-MM-DD`.

**Status lives in one place.** The board and the issue front matter must agree. plan.md never carries status.

## What goes where

| Situation | Where to record it |
|---|---|
| A new idea that isn't planned yet | BOARD.md → *Unplanned / ideas* |
| An idea that's been accepted | plan.md (a task in §21 and the design in the relevant section), plus a line in the changelog |
| A task about to be worked on | An issue file |
| A defect | `issues/BUG-nnn-….md`, with a line under *Ready* or *In progress* on the board |
| A choice between alternatives with lasting consequences | `decisions/nnnn-….md` |
| A complex feature that needs design before coding | `specs/…` |
| "What happened today" | log.md |
