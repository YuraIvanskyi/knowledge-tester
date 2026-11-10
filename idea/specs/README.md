# Specs

A spec is a detailed design for a feature that's too intricate to build from the plan's summary alone. Specs are written **just in time**, at the start of the phase that needs them. They expand the matching plan section rather than duplicate it, and once a spec exists, plan.md links to it.

## Planned specs

| Spec | Expands | Write before |
|---|---|---|
| `exchange-format.md`, which later becomes `docs/exchange-format.md` for users | plan §11 | Phase 1 (KT-102) |
| `editor-ux.md`: editor screens, HTMX interactions and mobile flows | plan §17, §21.4 | Phase 2 (KT-203) |
| `taker-flow.md`: screens, states, autosave and timer edge cases | plan §12 | Phase 3 (KT-305) |
| `grading.md`: the full rule matrix, rounding and an edge-case table that becomes the test table | plan §9, §10 | Phase 4 (KT-401) |
| `pdf-sheet.md`: an exact layout with measurements and options | plan §13.3 | Phase 5 (KT-502) |
| `llm-features.md`: prompts, output schemas and evaluation fixtures | plan §15 | Phase 7 (KT-701) |

## Spec outline

```markdown
# Spec: <feature>
- Status: Draft | Agreed (YYYY-MM-DD)
- Expands: plan.md §x · Tasks: KT-xxx…

## Problem and goals
## User-visible behaviour (screens / states / messages)
## Data and interfaces (models, JSON, function signatures)
## Edge cases and rules
## Test plan (cases that become automated tests)
## Open points
```
