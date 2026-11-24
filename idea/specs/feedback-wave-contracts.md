# Spec: classroom-test feedback wave (F-01 to F-10)

- Status: Built (2026-11-24); all ten items done, see the log entry of that day for what is open
- Source: the list of features found while testing in a classroom (2026-11-24)
- Method: frozen skeleton (this doc, `Attempt.away_*`, `taker:away`, reserved URLs), then three
  workstreams with disjoint file ownership; the orchestrator merges translations, runs the full
  suite, commits, and updates the board, log and README.

## The ten items

| Id | Item (as reported, uk) | What we build | Owner |
|---|---|---|---|
| F-01 | Кнопку «Надіслати» забрати зі стікі-футера | Submit sits at the end of the form; the sticky bar keeps the counter, timer and save status | WS-T |
| F-02 | «Усе одно надіслати» перекриває ввід імені | Reproduced: after Submit the name fields vanish and the confirmation panel takes their place at the top. Fix: confirm next to the Submit button at the end (inline with JS, no reload; server-side panel kept as the no-JS fallback, also at the end), and once the attempt exists a read-only "who is answering" line stays at the top | WS-T |
| F-03 | Перехід по питаннях маленькими кнопками замість текстових лінків | A question navigator: one small numbered button per question (answered / empty / current / required-missing states), used in the confirm panels and as the page navigation | WS-T |
| F-04 | Трекінг переходів | Leaving the test page (other tab or app, window loses focus) is counted with the time away. Student sees a short notice that leaving is recorded; teacher sees it live on the session screen, on the attempt sheet, in the results table and in the CSV | WS-T (page + JS), WS-R (teacher views) |
| F-05 | На вікні показу попап з іменем того, хто здав, на 5 секунд | Share screen (presentation mode and the normal page): a toast with the name of every newly finished attempt, 5 s each, queued | WS-R |
| F-06 | Дефолтний час на тест 30 хв | New tests in the browser start with 30 min (`editing.NEW_TEST_TIME_LIMIT`); prompts default to 30. Imported JSON keeps its own value | orchestrator (done in the skeleton) |
| F-07 | Генерувати PDF для письмової роботи | A printable test sheet (blank form for a paper test): header with the taker fields as blanks, each question with boxes or answer lines, one block per variant; optional answer key at the end | WS-P |
| F-08 | Налаштування «по одному питанню на сторінці» не працює | Client-side paging when `settings.one_question_per_page`: one question visible, Previous / Next, the navigator; without JS all questions show (as now) | WS-T |
| F-09 | Перехід стрілками між результатами | Attempt sheet: previous / next attempt buttons (order of the session results table, filter and sort carried along) and the keyboard arrow keys | WS-R |
| F-10 | Можливість перепідключення після надання відповіді (щоб інший юзер міг здати) | Done page: "Another student on this device" (POST `taker:another`) forgets this browser's attempt and opens the session landing page; the per-name / per-student attempt limits still apply | WS-T |

## Frozen skeleton (commit "Skeleton: feedback wave")

- `Attempt.away_count`, `Attempt.away_seconds` (PositiveIntegerField, default 0), migration
  `delivery/0004_attempt_away`. Written only by `services.record_away(attempt, count, seconds)`:
  adds deltas, clamps one report to `AWAY_MAX_COUNT` (20) and `AWAY_MAX_SECONDS` (4 h), ignores a
  finished attempt, atomic `F()` update, returns True when something was added.
- `taker:away`: POST `/s/<code>/away/`, JSON `{"attempt_token": "<uuid>", "count": n, "seconds": s}`
  (deltas since the last report). Attempt = cookie, else page token (`_attempt_of_page`). Replies
  `{"recorded": true|false}`; false = no attempt yet or finished (the page keeps the delta and
  sends it again after the attempt has started). 400 on a body that is not a JSON object. Never sets
  a cookie, never starts an attempt. CSRF: `X-CSRFToken` header like the autosave.
- `taker:another`: POST `/s/<code>/another/`, reserved (501 stub in `taker_urls.py`), WS-T builds it.
- `assessments:paper_pdf`: GET `/teach/tests/<pk>/paper/`, ownership-checked stub in
  `apps/assessments/paper_views.py` (200 placeholder), WS-P builds it. Already listed in
  `tests/test_ownership_audit.py`.
- `editing.NEW_TEST_TIME_LIMIT = 30`, `blank_document` sets it.

## Workstreams and file ownership

Agents never run git; the orchestrator commits. Every agent verifies on a live server with its own
data folder and port and its own headless Edge (`CDP_PORT`), see `scripts/ui_shots.mjs`.

| WS | Items | Owns (may edit) | Port / CDP |
|---|---|---|---|
| WS-T, student page | F-01, F-02, F-03, F-08, F-10, F-04 page side | `apps/delivery/taker_views.py`, `taker_urls.py`, `templates/delivery/take.html`, `done.html`, `session.html`, `_identity.html`, `static/css/delivery.css`, `static/js/autosave.js`, `static/js/timer.js`, new `static/js/questions.js`, new `static/js/away.js`, new tests in `apps/delivery/tests/` (`test_taker_*.py`), existing taker tests that the change breaks, `locale/uk/parts/feedback_taker.po` | 8211 / 9341 |
| WS-R, teacher screens | F-05, F-09, F-04 teacher side | `apps/delivery/services.py` (`session_stats` only), `apps/delivery/views.py`, `templates/delivery/share.html`, `static/js/share.js`, `static/css/sessions.css`, `apps/reports/views.py`, `apps/reports/data.py`, `templates/reports/attempt.html`, `templates/reports/session.html`, `static/css/reports.css`, new `static/js/sheetnav.js`, new tests in `apps/delivery/tests/test_share_*.py` and `apps/reports/tests/test_sheet_nav.py`, `test_away_views.py`, `locale/uk/parts/feedback_teacher.po` | 8212 / 9342 |
| WS-P, paper PDF | F-07 | new `apps/reports/paper_pdf.py`, `apps/assessments/paper_views.py`, `templates/assessments/detail.html` (one block near Preview / Export), new `templates/assessments/_paper_form.html`, `static/css/assessments.css` (only for that form), new `apps/reports/tests/test_paper_pdf.py`, `locale/uk/parts/feedback_paper.po` | 8213 / 9343 |

Shared read-only: everything else (`base.css`, `base.html`, `models.py`, the skeleton code).
Something needed outside your files: note it in your report instead of editing.

## Interfaces between the workstreams

- `services.session_stats(sitting)` (WS-R) adds per taker: `"id"` (attempt pk), `"away_count"`,
  `"away_seconds"`, `"submitted_at"` (ISO or null). Existing keys stay.
- The teacher sees away data only through WS-R; WS-T never shows the student their own counts
  beyond the notice that leaving is recorded.
- Translations: each WS writes msgid/msgstr pairs to its own fragment under `locale/uk/parts/`;
  the orchestrator runs `scripts/i18n.py extract`, `merge`, `check`, `compile` once.

## Rules that hold everywhere

- Works without JavaScript (the JS only improves); CSP: no inline scripts or styles
  (`tests/test_offline*.py`, `apps/reports/tests/test_pages_csp.py`).
- No correct answers in the taker page; phone first (390 px), tap targets 44 px except where the
  item asks for small buttons (navigator: at least 36 px, with spacing).
- Ukrainian and English UI strings through gettext; light and dark themes via base.css tokens.

## Test plan (minimum per item)

- F-01/F-02: the take page has no submit button inside `.sticky-bar`; the server-side confirm
  panel renders after the questions and keeps the "who is answering" line; the JS confirm (live).
- F-03: navigator rendered with one button per question, states right for answered / required.
- F-04: away.js reports on return; queued before the attempt exists; shown on share, sheet,
  results, CSV.
- F-05: stats carry ids and finish times; the toast appears for a new finish (live check).
- F-06: done in the skeleton (`test_new_test_starts_with_a_30_minute_limit`).
- F-07: PDF text read back with pypdf: questions, options, blanks, variant headers, key on/off,
  no correct answers without the key, ownership.
- F-08: page carries the one-per-page flag; paging live at 390 px; no-JS shows all.
- F-09: previous/next follow the results order with filter and sort; ends have no link.
- F-10: after `another`, the cookie is gone and the landing page shows; the same name still
  cannot take a one-attempt test twice; class sessions let the next student pick their name.
