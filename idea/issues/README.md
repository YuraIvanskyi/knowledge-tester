# Issues

There's one Markdown file per task or bug. The board ([../BOARD.md](../BOARD.md)) shows status at a glance, and the issue file holds the detail: context, scope, acceptance criteria and a working log.

## When to create an issue file

- **Planned tasks (`KT-…`):** when the task moves to *Ready*, usually for the whole next phase at once. Until then, the one-line entry in [plan.md §21](../plan.md#21-roadmap) and the board is enough.
- **Bugs (`BUG-…`):** as soon as they're found.
- **Anything needing discussion** before it's ready: create the file early with `status: backlog`.

## File rules

- Name: `KT-<id>-<short-slug>.md` or `BUG-<nnn>-<short-slug>.md`.
- Start from [_template.md](_template.md).
- Keep the front matter accurate. `status` must match the board.
- Acceptance criteria are checkboxes that can be verified. Tick them as they're met.
- The *Log* section collects dated one-liners: decisions, surprises, links to commits.
- Done issues stay in this folder for history. They're never deleted.

## Front matter fields

| Field | Values |
|---|---|
| `id` | `KT-101`, `BUG-001` |
| `title` | Short and imperative |
| `phase` | 0–9, or `-` for bugs outside the phases |
| `type` | `feature` · `chore` · `bug` · `spike` · `docs` |
| `status` | `backlog` · `ready` · `in-progress` · `review` · `done` · `blocked` |
| `priority` | `must` · `should` · `could` |
| `size` | `S` · `M` · `L` |
| `depends_on` | A list of IDs |
| `created`, `updated` | `YYYY-MM-DD` |
