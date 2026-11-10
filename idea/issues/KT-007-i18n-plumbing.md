---
id: KT-007
title: Set up i18n plumbing (English now, Ukrainian scaffold)
phase: 0
type: chore
status: ready
priority: must
size: S
depends_on: [KT-002]
created: 2026-11-10
updated: 2026-11-10
---

# KT-007: Set up i18n plumbing (English now, Ukrainian scaffold)

## Context
English ships first, but every string has to be translatable from day one, so Phase 8 is translation work rather than refactoring. See [plan.md §16](../plan.md#16-localization).

## Scope
- `USE_I18N`, `LocaleMiddleware` and `LANGUAGES = [("en", "English"), ("uk", "Українська")]`. The code for Ukrainian is `uk`, not `ua`.
- `LOCALE_PATHS` and a scaffold at `locale/uk/LC_MESSAGES/django.po`.
- The `set_language` view wired up, with a temporary switcher on the style guide page.
- Documentation:
  - how to install GNU gettext on Windows and run `makemessages` / `compilemessages`
  - compiled `.mo` files are committed, so end users don't need gettext
- Rules for contributors, added to the README: wrap every UI string, and use `ngettext` / `{% blocktranslate count %}` for anything with a count, because Ukrainian has three plural forms.

## Acceptance criteria
- [ ] `uv run manage.py makemessages -l uk` and `compilemessages` work, following the documented steps
- [ ] A test with a dummy `uk` translation shows a wrapped template string switching language
- [ ] Every template that exists at the end of Phase 0 has its strings wrapped

## Log
- 2026-11-10: created from the plan.
