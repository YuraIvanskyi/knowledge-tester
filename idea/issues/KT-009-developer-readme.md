---
id: KT-009
title: Write developer README and first-run docs
phase: 0
type: docs
status: ready
priority: must
size: S
depends_on: [KT-005]
created: 2026-11-10
updated: 2026-11-10
---

# KT-009: Write developer README and first-run docs

## Context
Getting a phone to reach the host is the step most likely to fail, because of firewalls, network profiles and Wi-Fi isolation. The README has to make it routine. See [plan.md §19](../plan.md#19-operations).

## Scope
The root `README.md` covers:
- What the app is, in a short paragraph, with a link to `idea/plan.md`.
- Requirements: Windows 10/11 (or Linux/macOS), uv, Git, and optionally GNU gettext and Ollama.
- Setup: `uv sync`, the virtual environment and data folder outside OneDrive, `migrate`, `createsuperuser`.
- Running in development (`runserver`) and on the LAN (`serve`).
- **Phone access checklist:**
  - set the network profile to Private
  - add the firewall rule (exact command)
  - recommended network setups, and the client-isolation warning (plan §19.2)
- The `KT_*` settings table and the data folder layout.
- Contributor conventions: tracking in `idea/`, the Definition of Done, the i18n rules, and the check script.

## Acceptance criteria
- [ ] Someone other than the author, or a fresh Windows user account, follows the README from a clean clone to a phone showing the login page
- [ ] Every command in the README has been run once and works as written

## Log
- 2026-11-10: created from the plan.
