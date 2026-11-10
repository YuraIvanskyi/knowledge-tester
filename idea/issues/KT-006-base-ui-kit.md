---
id: KT-006
title: Build base UI kit (layouts, CSS tokens, components)
phase: 0
type: feature
status: ready
priority: must
size: M
depends_on: [KT-002]
created: 2026-11-10
updated: 2026-11-10
---

# KT-006: Build base UI kit (layouts, CSS tokens, components)

## Context
Every later screen is built from this kit, and its look has to avoid the generic AI-generated style. **Read [plan.md §17](../plan.md#17-uiux-guidelines) first**, including the list of things to avoid, the visual system, the mobile rules and the performance budget.

## Scope
- `templates/base.html`, which:
  - sets `lang` and a correct viewport meta tag
  - loads no external URLs
  - renders the messages framework
  - adds the CSRF header for HTMX through `hx-headers` on `<body>`
- **Teacher layout:** a top bar with the name and navigation, collapsing into a simple menu on phones, with content at most about 60 rem wide.
- **Taker layout:** minimal, with room for a sticky bottom action bar.
- CSS files:
  - `tokens.css`: colors, spacing, type scale and radius, with dark mode through `prefers-color-scheme`
  - `base.css`
  - `components.css`
  - `print.css` (a stub)
- Components:
  - buttons: primary, secondary and danger
  - form fields with labels, help text and errors
  - choice rows where the whole row is the tap target
  - tables that turn into stacked rows on phones
  - alerts and messages
  - an empty state
  - pagination
  - the sticky action bar
- `static/vendor/htmx.min.js` 2.x, pinned, with its license file.
- A development-only style guide page at `/dev/ui/` that shows every component.

## Acceptance criteria
- [ ] The style guide renders correctly at 360, 768 and 1280 px, in light and dark mode
- [ ] No item from plan §17.2 appears (reviewed against the list)
- [ ] CSS totals 15 KB or less uncompressed. No web fonts and no icon fonts
- [ ] Tap targets are at least 44 px, input text is at least 16 px, and focus states are visible
- [ ] The offline guard test (KT-008) passes for the style guide page

## Log
- 2026-11-10: created from the plan.
