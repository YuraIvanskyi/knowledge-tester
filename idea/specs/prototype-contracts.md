# Prototype: shared contracts

Goal: a simplistic end-to-end prototype of the MVP flow: **import a test (JSON) -> publish -> open a session -> share link/QR -> students take it on phones -> autograde -> teacher sees results and reviews open answers**. Plan: [../plan.md](../plan.md). The skeleton (settings, models, URL wiring) is frozen; four workstreams fill it in without touching each other's files.

## Running things (Windows, from the repo root)

```bash
export UV_PROJECT_ENVIRONMENT="$LOCALAPPDATA/KnowledgeTester/venv"
python -m uv run manage.py <cmd>      # uv is not on PATH; always use `python -m uv`
python -m uv run pytest
python -m uv run ruff check . && python -m uv run ruff format .
```

## Frozen shared files (do not edit; report what you need in your final message)

`config/settings/*`, `config/urls.py`, all `models.py`, all `migrations/`, `pyproject.toml`, `apps/core/lan.py`.
If you truly need a model field or a new dependency, work around it and say so in your final report.

## Data model (prototype simplification)

No Question/Option tables. A test's content is its **Test Document** (plan §11) as JSON:
`Assessment.document` (editable draft) and `Revision.document` (immutable published snapshot, `Revision.test` = the inner `test` object).
**Every question and option in a stored document has an `id`** (the importer generates `q1..`, `a..` if missing). Models: [apps/assessments/models.py](../../apps/assessments/models.py), [apps/delivery/models.py](../../apps/delivery/models.py).

## Ownership

| Workstream | Owns (only edit these) |
|---|---|
| **A: exchange + assessments** | `apps/exchange/**`, `apps/assessments/**` (except models/migrations), `templates/assessments/**`, `docs/**`, `static/css/assessments.css` |
| **B: grading + reports** | `apps/grading/**`, `apps/reports/**`, `templates/reports/**`, `static/css/reports.css`, `static/css/print.css` |
| **C: delivery** | `apps/delivery/**` (except models/migrations), `templates/delivery/**`, `static/css/delivery.css`, `static/js/**` |
| **D: core + accounts + UI kit + serve** | `apps/core/**` (except lan.py), `apps/accounts/**` (except models/migrations), `templates/base.html`, `templates/core/**`, `templates/registration/**`, `static/css/base.css`, `scripts/**`, `tests/**`, root `conftest.py`, `README.md` |

Each workstream puts its tests next to its code (`apps/<app>/tests/test_*.py`; add `__init__.py`).

## URL names (fixed; reverse them with these names)

| Name | Path | Owner | Notes |
|---|---|---|---|
| `core:landing` | `/` | D | "Enter session code" box (POSTs to `taker:enter`); logged-in teachers are redirected to the dashboard |
| `core:dashboard` | `/teach/` | D | teacher home: links to tests, sessions, import |
| `core:healthz` | `/healthz` | D | |
| `accounts:login`, `accounts:logout` | `/accounts/login/`, `/accounts/logout/` | D | logout is POST |
| `assessments:list` | `/teach/tests/` | A | projects + tests of the current user |
| `assessments:import` | `/teach/tests/import/` | A | paste/upload JSON -> report -> create draft |
| `assessments:detail` | `/teach/tests/<int:pk>/` | A | summary, validation, publish button, revisions, "Open session" per revision |
| `assessments:publish` | `/teach/tests/<int:pk>/publish/` | A | POST: creates the next `Revision` |
| `assessments:export` | `/teach/tests/<int:pk>/export/` | A | JSON download |
| `delivery:list` | `/teach/sessions/` | C | my sessions |
| `delivery:create` | `/teach/sessions/new/<int:revision_pk>/` | C | form (title, access code, optional time limit override) -> creates `Sitting` |
| `delivery:share` | `/teach/sessions/<int:pk>/` | C | QR, URL, code, live counters, takers table, close button |
| `delivery:close` | `/teach/sessions/<int:pk>/close/` | C | POST |
| `reports:session` | `/teach/results/session/<int:sitting_pk>/` | B | summary + attempts table |
| `reports:attempt` | `/teach/results/attempt/<int:pk>/` | B | the sheet + review form |
| `reports:csv` | `/teach/results/session/<int:sitting_pk>/csv/` | B | |
| `taker:enter` | `/s/enter/` | C | POST `code` -> redirect to `taker:session` |
| `taker:session`, `taker:take`, `taker:submit`, `taker:done` | `/s/<code>/...` | C | public taker flow |

Templates may link to other workstreams' URL names even before they exist; once everyone is done they all resolve. In tests, don't `reverse()` another workstream's names unless those views already exist (use `pytest.importorskip`-style guards or test your own views only).

## Python interfaces between workstreams

**A -> everyone** (`apps/exchange/`):
- `apps.exchange.importer.import_document(data: str | bytes | dict) -> ImportResult`
  `ImportResult.document: dict | None` (normalised canonical Test Document, all ids present), `.report: ValidationReport`, `.ok: bool`.
  `ValidationReport.errors/.warnings` are lists of `Issue(path, message)`; `.as_text()` is pasteable to an LLM. Messages are plain: "questions[1] (id "q2", multiple_choice): no option is marked correct. Add "correct": true to at least one option."
- Test Document format = plan §11 exactly (single_choice, multiple_choice, choose_n, short_answer, open).

**B -> C** (`apps/grading/`):
- `apps.grading.engine` (pure Python, no Django): `grade_answer(question: dict, value) -> AnswerResult(points: Decimal, max_points: Decimal, status: "graded"|"needs_review"|"unanswered")` and `grade_test(test: dict, answers: dict[str, object], manual_scores: dict[str, Decimal] | None = None) -> TestResult(score, max_score, percent, grade, pending_reviews, per_question: dict[str, AnswerResult])`. `test` is the inner `test` object; rules exactly per plan §9, normalisation §9.3, grade scales §10.
- `apps.grading.service.grade_attempt(attempt) -> None`: loads `attempt.sitting.revision.test` and its `Answer` rows, creates missing `Answer` rows for unanswered questions, writes `auto_score`/`status` on each answer (a set `manual_score` wins), writes totals on the attempt (`score, max_score, percent, grade, pending_reviews`). Idempotent. **C calls this when an attempt is submitted or auto-finalised.**

**C -> B/A/D**: `Sitting`/`Attempt`/`Answer` rows as in models; answers values: choice types = list of option ids, `short_answer`/`open` = string. `Attempt.question_order` holds the question ids as shown to the taker.

## UI / CSS vocabulary (D defines it in `static/css/base.css`; everyone uses it)

Base template blocks: `title`, `head` (extra `<link>`s), `nav`, `content`, `scripts`.
Classes: `.container`, `.stack` (vertical rhythm), `.row` (flex wrap), `.btn`, `.btn-primary`, `.btn-danger`, `.btn-link`, `.field` (label + input wrapper), `.table` (reflows to stacked rows below 640px), `.muted`, `.alert`, `.alert-ok|warn|bad`, `.status-ok|warn|bad` (text colour for correctness/status; always with a word beside it), `.sticky-bar` (bottom action bar), `.mono`, `.big-code`.

## Rules for everyone (plan §5.2, §17, §18, §20.2)

- **Offline:** no CDNs, web fonts, external URLs. **CSP is `default-src 'self'`:** no inline `<style>`, `style=""`, inline `<script>` or `onclick=` handlers. Inline SVG in HTML is fine. JS only in `static/js/*.js` and optional; taker flow must work without JS.
- **UI:** system fonts, one accent colour, no gradients/shadows/glass, radius <= 6px, no emoji, no coloured left-border cards, no cards in cards. Start from 360px wide; tap targets >= 44px; inputs >= 16px font.
- **i18n:** wrap every user-visible string (`{% trans %}`, `gettext`/`gettext_lazy`).
- **Permissions:** every teacher view needs `@login_required` and an ownership check (a teacher only sees their own projects/tests/sessions/results; `user.role == "admin"` sees all). Taker pages need no login, but never leak correct answers before the test's `show_result` allows it.
- CSRF on every form. Use Django's ORM; keep taker pages to few queries.
- Tests (pytest) for your logic. `ruff check .` and `ruff format .` must pass before you finish.
- Do **not** run `git commit`/`git add`; the orchestrator commits. Do not leave the dev server running.
- Keep it **simplistic**: prototype quality, working end to end beats feature-complete. Skip anything marked Should/Could in the plan.
