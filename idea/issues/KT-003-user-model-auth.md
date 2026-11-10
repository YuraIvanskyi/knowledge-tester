---
id: KT-003
title: Add custom User model, roles and auth screens
phase: 0
type: feature
status: ready
priority: must
size: M
depends_on: [KT-002, KT-004]
created: 2026-11-10
updated: 2026-11-10
---

# KT-003: Add custom User model, roles and auth screens

## Context
Django strongly recommends a custom user model before the first migration, because changing it later is painful. The roles come from [plan.md §2](../plan.md#2-users-and-roles).

## Scope
- `accounts.User(AbstractUser)` with these fields:
  - `role`: `admin` or `teacher`, default `teacher`
  - `display_name`
  - `ui_language`: blank means "follow the browser"
- `AUTH_USER_MODEL = "accounts.User"`, then the initial migrations for all apps.
- `createsuperuser` produces a user with `role=admin`.
- Login, logout (POST only) and password change, using project templates (they get styled in KT-006).
- Access helpers: a `TeacherRequiredMixin` and `AdminRequiredMixin`, plus decorator equivalents.
- Redirects: `/teach/` sends anonymous users to login, and login lands on `/teach/`.

**Out of scope:** teacher management screens (KT-601) and login throttling (KT-904).

## Acceptance criteria
- [ ] `AUTH_USER_MODEL` is set before any migration exists, and the migrations are committed
- [ ] `createsuperuser` creates an admin-role user
- [ ] The login page works at 360 px width, shows a clear message for wrong credentials, and supports the "next" redirect
- [ ] Tests cover role helpers, anonymous redirects, logout by POST only, and a teacher being refused on `/manage/`

## Log
- 2026-11-10: created from the plan.
