# UX review wave: plan and shared contracts

- Status: Wave 0 and workstreams A to E built and committed (2026-11-13); integration gate closed 2026-11-13, see [../log.md](../log.md)
- Expands: [plan.md §17](../plan.md#17-uiux-guidelines), §12.3, §12.6, §13.1, §13.2 · Tasks: UX-01 to UX-18
- Read first: [prototype-contracts.md](prototype-contracts.md) (UI vocabulary, CSP, offline, i18n, ownership) and [people-contracts.md](people-contracts.md) (data rules). This file only adds what is new.

Goal: **a lesson cannot be damaged by one wrong tap, the teacher's main job (open a session, review, read results) is one obvious step from where they are, and phone pages are about half as long.**

## 1. Where this comes from

On 2026-11-13 the whole app was used end to end in headless Edge at 390 px and 1280 px, in Ukrainian, light and dark: a teacher imported a class of 12, generated PINs, opened three sessions (free-name, class with PIN, class without PIN), 22 simulated students took them on a phone viewport, and the teacher then used the live screen, results, review, linking, gradebook, profile and the admin area. No code was changed. The findings are the 18 tasks below. Each one says what was observed, so nobody has to rediscover it.

Baseline measurements from that run (Ukrainian, 390 × 844, seeded demo data). Use them to prove a change worked:

| Page | Baseline | Data on the page |
|---|---|---|
| `assessments:detail` | 4,088 px tall | 11 questions |
| `reports:session` | 4,906 px tall | 8 attempts, 11 questions |
| `people:import` preview | 2,985 px tall | 13 rows |
| `delivery:share` | 2,100 px tall | 8 takers |
| `delivery:list` | page is 425 px wide (scrolls sideways) | 3 sessions |
| Taker bottom bar | about 105 px tall (two rows) | timer shown |
| Header, admin user | 133 px (three rows) at 390 px; two rows at 700 px | six nav items |

## 2. Decisions already made (do not reopen)

1. **No model changes and no migrations.** Everything here is views, templates, CSS and small JS.
2. **No-JS first, as before.** Every new confirmation is a server-rendered step. JS only adds comfort (save status, timer warning).
3. **Submitting with unanswered questions asks once**, on the server (UX-01). A deadline-driven submit never asks.
4. **A teacher can cancel ("void") an attempt, and a cancelled attempt never blocks a new one.** Cancelling is not reversible in this wave; the confirmation page says so. The `VOIDED` status and every "voided never counts" rule already exist.
5. **Closing a session asks only when somebody is still working** (UX-02).
6. **A session is opened from a published test's latest revision.** New chooser page `delivery:pick`; `delivery:create` accepts `?group=<pk>`.
7. **Top navigation is Tests · Sessions · People (· Manage for admins).** "Import" stops being a top-level item; it stays as a button on the Tests page and the dashboard.
8. **Narrow pages are centred** on wide screens (landing, login, all single-column forms).
9. **Phone tables use a card pattern** defined once in `base.css` (§5); templates opt in with classes.
10. **Review stays per attempt** in this wave, but with one Save for the whole sheet. Reviewing one question across all students is out of scope.
11. Visual rules of plan §17 stay: system fonts, one accent, no shadows or gradients, radius ≤ 6 px, no emoji, no icon fonts. Text arrows (`↑`, `↓`, `←`) are allowed.

Out of scope: restoring a voided attempt, review-by-question, one-question-per-page, a JS menu component, any change to PDF output, new question types.

## 3. Running things (Windows, from the repo root, bash tool)

```bash
export UV_PROJECT_ENVIRONMENT="$LOCALAPPDATA/KnowledgeTester/venv"
python -m uv run pytest apps/<your app> tests/test_offline_<you>.py     # full suite takes ~80 s
python -m uv run ruff check . && python -m uv run ruff format .
python -m uv run manage.py check
```

Python text IO defaults to cp1252 on this machine: always pass `encoding="utf-8"`, and prefer the Edit/Write tools for source files.

## 4. Wave 0: skeleton (orchestrator, alone, committed before anyone else starts)

The skeleton is everything two workstreams would otherwise both have to touch.

1. **`static/css/base.css`**
   - `.alert`: replace `margin: 0 0 var(--space-4)` by `margin-bottom: var(--space-4)` only. The shorthand currently cancels the `.stack` gap, so warnings touch the element above them (seen on results and profile). (UX-12)
   - `.container-narrow`: add `margin-inline: auto`. (UX-13)
   - Add the phone card pattern of §5. (UX-11)
   - Move here, unchanged, the rules that are duplicated in page files: `.subnav` (from `people.css` and `manage.css`), `.tap` (from `people.css`), `[hidden] { display: none !important; }` (from `delivery.css` and `people.css`). The owners delete their copies.
   - Add `.link-tap` (`display: inline-flex; align-items: center; min-height: 44px;`) for standalone text links such as "Back to tests" and "Cancel". `.lang-switch button` gets `min-width: 44px; justify-content: center`. (UX-18)
   - Top bar as described next.
2. **`templates/base.html`** (UX-09)
   - Remove the "Import" nav link. `aria-current` on Tests now also covers the `assessments:import` page.
   - Take the log-out form out of `<nav>` into a new `.topbar-user` block next to the language switch: user name (hidden below 640 px) and a "Log out" button without the name in brackets.
   - Result to verify for an **admin in Ukrainian**: at 390 px two rows (brand + Log out; then the four nav links on one line), at 700 px and wider one row. Language switch behaviour is unchanged (header from 640 px, footer below).
3. **`apps/delivery/services.py`**: add `void_attempt(attempt) -> bool` (sets `status = VOIDED` unless it already is; returns whether it changed; touches nothing else, so the score stays visible to the teacher). Unit tests in `apps/delivery/tests/test_void.py`.
4. **Reserved URL names**, pointing at `apps.core.stubs.not_implemented` until their owner replaces them:
   - `delivery:pick` → `/teach/sessions/new/` (owner B)
   - `reports:attempt_void` → `/teach/results/attempt/<pk>/void/` (owner C)
5. **Split `static/css/delivery.css`**: move the share screen, counters, `.check-field` and linking-table rules into a new `static/css/sessions.css` and load it, in addition to `delivery.css`, in `templates/delivery/{list,share,create,link,confirm_delete}.html`. `delivery.css` keeps the taker rules and the helpers both sides use (`.facts`). The split exists so that A and B never edit the same file. No visual change.
6. Run the full suite and `ruff`, look at the dashboard, a People page and a Manage page at 390 / 700 / 1280 px, commit.

`scripts/ui_shots.mjs` (a headless-Edge driver, usage in its header) already exists for step 6 and for §8.

## 5. Phone card pattern (defined in Wave 0, applied by every workstream)

Today every cell of a stacked row is its own "label … value" line, which is why phone pages are so long. Below 640 px:

| Class | On | Effect below 640 px |
|---|---|---|
| `cell-title` | the `td` that names the row (test, student, session) | No `data-label` text, left aligned, weight 600, full width, flows as inline text: the card's heading |
| `cell-actions` | the `td` holding links or buttons | No label, left aligned, full width, flows as inline text (links wrap with their " · " separators) |
| `table-compact` | the `table` (together with `.table`) | The remaining labelled cells flow as one wrapped line of "Label: value" pairs instead of one line each |

Checked on the real sessions table at 390 px (three sessions): no sideways scroll, 865 px tall.

Desktop rendering does not change. Rules for templates: every stacked table gets exactly one `cell-title`; action cells get `cell-actions`; add `table-compact` wherever the other cells are short (numbers, dates, statuses). A cell that can hold long text (a question, a note) stays a normal labelled cell.

## 6. Ownership (edit only your own paths; everything else is read-only)

Frozen for everyone after Wave 0: `config/**`, every `models.py` and `migrations/`, `pyproject.toml`, `apps/delivery/services.py`, `apps/core/stubs.py`, `templates/base.html`, `templates/core/_lang_switch.html`, `static/css/base.css`, `tests/test_offline.py`, `tests/test_smoke.py`, `conftest.py`, `scripts/**`, `locale/uk/LC_MESSAGES/**`, `README.md`, `idea/**`. If you truly need a change there, work around it and say so in your final report.

The orchestrator commits, compiles translations and updates README / BOARD / log. **Workstreams never run `git add`, `commit`, `stash` or `checkout`.** Others edit the same working tree: if an unrelated test fails because of someone's half-finished work, re-run later; never fix files you do not own.

| WS | Area | Tasks | Owns |
|---|---|---|---|
| **A** | Student test page | UX-01 (taker part), 03, 05, 10, 15 | `apps/delivery/taker_views.py`, `taker_urls.py`, `roster.py`; `templates/delivery/{take,_identity,session,done,enter_error}.html`; `static/js/{autosave,timer,namepicker}.js`; `static/css/delivery.css`; `apps/delivery/tests/test_{taker,direct,group_taker,group_pin}.py` and new `test_submit_confirm.py`; `locale/uk/parts/ux_taker.po`; new `tests/test_offline_taker.py` |
| **B** | Teacher sessions | UX-02, 04, 06 (chooser, `?group=`, Sessions page), 16 | `apps/delivery/views.py`, `urls.py`, `forms.py`, `linking.py`; `templates/delivery/{list,share,create,link,confirm_delete}.html`, new `confirm_close.html` and `pick.html`; `static/js/share.js`; `static/css/sessions.css`; `apps/delivery/tests/test_{teacher,manage,group_create,linking}.py` and new files; `locale/uk/parts/ux_sessions.po`; `tests/test_offline_linking.py` |
| **C** | Results and review | UX-01 (teacher part), 07, 17 | `apps/reports/**`; `templates/reports/**`; `static/css/{reports,print}.css`; `locale/uk/parts/ux_results.po` |
| **D** | Tests and dashboard | UX-06 (test page, tests list, dashboard), 08 | `apps/assessments/**` except `models.py` / `migrations`; `apps/core/views.py`, `apps/core/tests/test_views.py`; `templates/assessments/**`, `templates/core/{dashboard,landing}.html`; `static/css/assessments.css`; `locale/uk/parts/ux_tests.po` |
| **E** | People and admin | UX-06 (group page), 09 (sub-tabs), 14 | `apps/people/**` except `models.py` / `migrations` / `names.py` / `access.py`; `apps/accounts/**` except `models.py` / `migrations`; `templates/people/**`, `templates/manage/**`, `templates/registration/**`; `static/css/{people,gradebook,profile,manage}.css`; `locale/uk/parts/ux_people.po`; `tests/test_offline_{roster,profile,gradebook,manage}.py` |

Every workstream also does the shared items of §7.6 in its own templates. Work the tasks in the order of the priority column: `must` first.

**One cross-workstream rule about tests:** after UX-01, a POST to `taker:submit` that leaves questions unanswered re-renders the page instead of finishing. Tests that mean "finish this attempt" must post `confirm_unanswered=1`. A owns the taker tests; B fixes the two places in `test_teacher.py`.

## 7. Tasks

Sizes: S ≤ half a day, M 1–2 days. Each acceptance list also implies the Definition of Done in [plan.md §20.2](../plan.md#202-definition-of-done-every-issue).

### 7.1 Workstream A: student test page

**UX-01 (taker part) · must · M: ask before submitting unanswered questions; a cancelled attempt does not block a new one**

Observed: one tap on "Надіслати" with nothing answered finished the attempt as 0 / 16. With the default `max_attempts = 1` the student is then sent to the result page forever.

- In `taker_views.submit`, after the existing `missing` (required questions) check and before `finalize`: if any question is unanswered and the POST has no `confirm_unanswered`, re-render the test page (answers already saved) with a warning panel at the top: how many of how many are answered, links to the unanswered questions (same pattern as the `missing` list), a primary button "Submit anyway" (`name="confirm_unanswered" value="1"`, submits the same form) and the hint to keep answering. Set focus target / anchor so the panel is what the student sees after the reload.
- Never ask when the attempt is past its deadline (that branch already finalises first). `timer.js` adds a hidden `confirm_unanswered=1` before its automatic `form.submit()`.
- The first-submit path of an unstarted page (`unstarted=1`) behaves the same: the attempt is created, answers are saved, the panel is shown.
- Preview mode (`render_preview`) is unaffected.
- Cancelled attempts: in `taker_views.session`, a cookie attempt with status `VOIDED` counts as "no attempt" while the session is open: show the unstarted test page with a note that the teacher cancelled the previous attempt. `done.html` for a voided attempt links to "Take the test again" when the session is open. `take` with a voided attempt redirects to `done`.

Acceptance:
- [ ] Posting an empty or partly answered form does not finish the attempt; the page shows the panel with correct counts and working links; posting again with `confirm_unanswered=1` finishes it.
- [ ] A fully answered form finishes in one POST, as today.
- [ ] Past the deadline, any submit finishes without asking; the timer's automatic submit never shows the panel.
- [ ] After `void_attempt`, the same browser can start a new attempt in an open session (free-name and class sessions); name-based `max_attempts` still ignores the voided one.
- [ ] Works with JavaScript disabled.

**UX-03 · must · S: show that answers are saved, and warn before time runs out**

Observed: `autosave.js` retries silently when a request fails; the student never learns whether anything was saved. `timer.js` counts to zero without any warning and then submits.

- A status element in the bottom bar (`role="status"`, `aria-live="polite"`, texts passed as `data-` attributes, as `share.js` does with `data-of`): empty until the first save, then "Saved"; "No connection: answers will be sent when it is back" after a failed request or the browser's `offline` event; back to "Saved" after the next success.
- Timer: at 60 s left add a warning style (the `--bad` colour plus bold) and announce "1 minute left" once through a visually hidden live region. Colour is not the only signal: the announcement text also appears next to the timer for a few seconds or stays as a label.
- Without JS nothing new is shown.

Acceptance:
- [ ] Blocking the save URL (or stopping the server) shows the no-connection text within one retry; restoring it returns to "Saved" and no answer is lost.
- [ ] With a 1-minute test the warning state and the announcement appear immediately; with a longer test, at 60 s.
- [ ] Taker JS stays within the plan's budget (≤ 25 KB gzipped) and is never required to submit.

**UX-05 · must · S: one-row bottom bar on phones**

Observed: counter, timer and Submit wrap into two rows, about 105 px of an 844 px screen.

- One row: counter (`11 / 11`), timer (`19:58`), Submit. The words "Answered" and "Time left" become visually hidden below 480 px (still read by screen readers). The save status of UX-03 is a small second line under the counter, not a third column.

Acceptance:
- [ ] Bar height ≤ 72 px at 360 px and 390 px wide, in Ukrainian, with timer and save status visible (baseline about 105 px). Judge with a viewport screenshot, not a full-page one.
- [ ] Submit stays ≥ 44 px tall; nothing overlaps at 320 px.

**UX-10 · should · S: class-session identity form**

Observed: the PIN field is `type="password" maxlength="8"` with no numeric hint, so phones open the full keyboard for a 4-digit PIN. The optional "Клас" field is still asked although the class is known from the session.

- PIN input: add `inputmode="numeric"` and `pattern="[0-9]*"`. Keep `maxlength="8"` (the model allows 8).
- In class sessions do not ask taker fields whose key is `class` or `group`; store the session's group name in `taker[<that key>]` so results and CSV keep the column filled. Extend the existing `name` exclusion in `_identity_context` and `_start_errors`; keep both in step.

Acceptance:
- [ ] In a class session the form shows name picker, PIN (when required) and only the remaining fields; the attempt's taker data contains the group name under the skipped key.
- [ ] Free-name sessions are unchanged.

**UX-15 · should · S: question titles that wrap**

Observed: a `legend` longer than one line straddles the fieldset border on phones (first line on the border, the rest inside).

- Keep `fieldset` / `legend` (plan §17.5). Make the legend sit inside the box (`float: left; width: 100%; padding: 0;` with the following element clearing it), border and padding on `.question`.

Acceptance:
- [ ] One-line and three-line question titles both sit fully inside the box at 360 px and 1280 px, light and dark. Preview page included.

### 7.2 Workstream B: teacher sessions

**UX-02 · must · S: confirm closing while students are still working**

Observed: "Закрити сесію" is one click with no confirmation and force-submits every attempt in progress. It is a red button next to an equally red "Видалити".

- `delivery:close` (POST): if the session has attempts in progress and the POST has no `confirm`, render `confirm_close.html` (how many students are still working, that their answers so far will be submitted, that the session can be reopened but those attempts stay finished) with "Close session" (`confirm=1`) and "Cancel". With nobody in progress it closes at once, as today.
- On the share page "Close session" becomes a plain `.btn`; "Delete" stays `.btn-danger` but moves to the end of the row, after "All sessions", visually apart.
- The success message uses `ngettext` (today it says "attempt(s)", which breaks the README's plural rule).

Acceptance:
- [ ] Closing with one attempt in progress shows the confirmation and changes nothing until confirmed; with none it closes directly.
- [ ] GET on `delivery:close` is still rejected; foreign session ids still return 404.

**UX-04 · must · S: sessions list on phones**

Observed: the links cell ("Поділитися · Результати · Прив'язати до учнів · Видалити") does not wrap, so the page is 425 px wide in a 390 px viewport.

- Apply §5: session title is `cell-title` (class name after it, muted), links are `cell-actions`, table is `table-compact`. "Delete" is the last link.

Acceptance:
- [ ] `scrollWidth == clientWidth` at 360 px and 390 px with three sessions in Ukrainian.

**UX-06 (sessions part) · must · M: open a session from where the teacher is**

Observed: the only way to open a session is the "Версії" table at the bottom of a test page. The Sessions page has no primary action.

- `delivery:pick` (`/teach/sessions/new/`, optional `?group=<pk>`): the teacher's published tests, newest first, each with question count, time limit and an "Open session" link to `delivery:create` for its **latest** revision (passing `?group=` on). A test with unpublished changes says that the session will use the last published version. Empty state links to the Tests page. Admins see all tests, as elsewhere.
- `delivery:create`: read `?group=<pk>`; if it is one of the user's groups, preselect it. Anything else is ignored silently.
- Sessions page: primary button "Open a session" → `delivery:pick`. The empty state uses the same button.

Acceptance:
- [ ] From the Sessions page a session can be opened in three steps (button, choose test, confirm form).
- [ ] `?group=` preselects an own group and ignores a foreign or malformed id (no 404, no leak).
- [ ] `delivery:pick` lists only own published tests for a teacher.

**UX-16 · should · M: share screen**

Observed: at projector size the URL breaks mid-path (`…/s/` then `H3M7YK/`); on a phone each taker takes three labelled lines; "Надіслано" and "Виконується" look the same.

- The code is the main element; the URL is one line (`white-space: nowrap`, font size scaled with `clamp()` so it fits from 360 px up).
- Projector mode: `?present=1` renders the same page without the nav and the taker table (QR, URL, code, the three counters, a link back). No JS needed. Link to it from the normal page.
- Takers table: §5 (name is `cell-title`, status and answered count on one line). Submitted status uses `.status-ok`; in progress stays plain. `share.js` builds the same markup and classes as the template.

Acceptance:
- [ ] URL on one line at 360, 390, 1280 px; QR still scans (unchanged SVG).
- [ ] Share page with 8 takers at 390 px is at least 40 % shorter than the 2,100 px baseline.
- [ ] After a poll, rows rendered by `share.js` look the same as server-rendered ones.

### 7.3 Workstream C: results and review

**UX-01 (teacher part) · must · S: cancel an attempt**

- `reports:attempt_void`: GET shows a confirmation page (student name, score if any, "this cannot be undone; the student can then take the test again while the session is open"), POST calls `services.void_attempt` and returns to the session results with a success message. Same permission check as `attempt_sheet` (404 for foreign ids).
- Entry point: a "Cancel attempt" button on the attempt sheet (`.btn-danger`, at the end of the top row). Not shown for an attempt that is already voided.

Acceptance:
- [ ] A voided attempt disappears from the default results list, counts, averages, gradebook and profile (already the rule) and is visible under the "Voided" filter.
- [ ] Together with A: the student can start again.

**UX-07 · must · M: review a whole sheet with one Save**

Observed: every open answer has its own form and Save button, one page reload per answer. A class of 30 with two open questions is 60 saves. The sheet's heading is the test title; the student's name is small print.

- One form around all reviewable rows. Fields `points_<question id>` and `comment_<question id>`. An empty points field means "leave this answer as it is". Two submit buttons at the end: "Save" (stay on the sheet) and "Save and go to the next unreviewed attempt" (only when there is one; when there is none after saving, return to the session results with a message that everything is reviewed).
- Validation is per row: valid rows are saved, invalid ones are reported with the question number and keep what was typed.
- Heading: the student's name is the `h1`; test title, session and attempt code go to the sub-line. Page `<title>` already starts with the name.
- Result line under the header gets normal spacing (today score, grade and the provisional note run together).

Acceptance:
- [ ] Two open answers on one sheet are graded with one POST; `pending_reviews` and the provisional flag update as before.
- [ ] "Save and next" walks through all attempts that need review and ends on the results page.
- [ ] Out-of-range points on one row do not block the other row.
- [ ] Print stylesheet still hides the review form.

**UX-17 · should · S: results page polish**

- Filter: the "Show" select is as wide as its content, not the full row.
- Sort links: the active column shows `↑` or `↓` and its `th` has `aria-sort`.
- One flag per state: keep "(needs review)" in the Status cell; in the Score cell replace the word "provisional" by `*` and explain it in one line under the table (the gradebook already does this).
- Apply §5 to the attempts table (name is `cell-title`, "Open" is `cell-actions`) and to the questions table (`table-compact`; the question text stays a full labelled cell).

Acceptance:
- [ ] Results page with 8 attempts and 11 questions at 390 px is at least 40 % shorter than the 4,906 px baseline.
- [ ] CSV and PDF output unchanged.

### 7.4 Workstream D: tests and dashboard

**UX-06 (tests part) · must · M: "Open session" where the test is**

Observed: on a published, unchanged test the primary button is still "Опублікувати". The dashboard's primary action is "Імпортувати тест"; the Tests page's is "Новий тест".

- Test page, by state:
  - never published: primary "Publish";
  - published, no unpublished changes: primary "Open session" (latest revision); no Publish button, a muted "Published, version N" instead;
  - published with unpublished changes: primary "Publish changes", secondary "Open session (version N)".
- Tests list and the dashboard's "Recent tests": an "Open session" link per published test, straight to `delivery:create` for the latest revision (provide it from the view; do not query in the template).
- Dashboard: primary button "Open a session" (`delivery:pick`), then "New test" and "Import a test". The "No open sessions" text links to `delivery:pick`.

Acceptance:
- [ ] From the dashboard a session for an existing test can be opened in two steps.
- [ ] Each of the three test states shows exactly one primary button.
- [ ] Query count of the tests list does not grow with the number of tests.

**UX-08 · should · M: question rows**

Observed: every row has Edit, Up, Down, Duplicate and a red Delete: 4,088 px on a phone for 11 questions.

- The question text already links to the editor: drop the Edit button.
- Up / Down stay as compact buttons (`↑`, `↓`, with the existing `aria-label`s, ≥ 44 px).
- Duplicate and Delete go into a native `<details>` in the actions cell (summary "More"); Delete is a plain link there, not a red button.
- §5: question text is `cell-title` (number in front), type and points on one compact line, actions in `cell-actions`.
- The revisions table moves above "Add a question" only if it helps; the session entry point is now the header button (UX-06).

Acceptance:
- [ ] Test page with 11 questions at 390 px is at least 40 % shorter than the 4,088 px baseline.
- [ ] Reorder, duplicate and delete work without JS and keep their confirmation pages.

### 7.5 Workstream E: people and admin

**UX-06 (group part) · must · S.** The group page's "Запустити сесію для цієї групи" panel is a paragraph of instructions. Replace it by a primary button "Open a session for this group" → `delivery:pick?group=<pk>`, keeping the line about how many sessions are bound to the group.

**UX-09 (sub-tabs) · should · S.** People puts its sub-tabs above the page title, Manage below it. Use the People order everywhere (sub-tabs directly under the top bar, then the title). Delete the local `.subnav`, `.tap` and `[hidden]` copies now living in `base.css`.

**UX-14 · should · S.** The gradebook widens `main` to 80rem while the top bar stays at 60rem, so header and content do not line up. In `gradebook.css` widen `.topbar-inner` to the same 80rem on that page.

Apply §5 to: groups list, group page (student is `cell-title`), students list, **import preview** (name is `cell-title`; group and check result on one line; the tick box stays ≥ 44 px), PIN list, teachers list (which also needs normal left padding in its first column on desktop: today the text touches the border).

Acceptance:
- [ ] Import preview with 13 rows at 390 px is at least 40 % shorter than the 2,985 px baseline; duplicate and invalid rows keep their background and their text label.
- [ ] Gradebook header and matrix share the same left edge at 1280 px.
- [ ] Group page button opens the chooser with the group preselected in the next step.

### 7.6 Shared items (every workstream, own templates only)

- **UX-11 · should:** apply the card pattern of §5 to every stacked table you own.
- **UX-18 · could:**
  - Standalone text links ("Back to …", "Cancel", "← …") get `.link-tap`.
  - Small radios / checkboxes outside a `.choice` row (the "correct option" marks in the question editor, the import tick boxes) are wrapped in `label.tap`.
  - Page titles follow one form: `<page> - Knowledge Tester`.
  - Counts in messages go through `ngettext`.

## 8. Verification (mandatory, not optional)

pytest proves the rules; it does not show a page. Each workstream:

1. Boots its own instance: `export KT_DATA_DIR="<scratchpad>/ws-<letter>"`, `migrate`, `seed_demo` (users `teacher` / `teacher`, `admin` / `admin`), `runserver 127.0.0.1:<port> --noreload` in the background. Ports: A 8201, B 8202, C 8203, D 8204, E 8205; Edge debugging ports 9331 to 9335 in the same order (`CDP_PORT`). Stop both when done.
2. Drives the real flow with `scripts/ui_shots.mjs` (usage in its header): log in, create what the page needs through the UI or a small setup script, and for a student use `newPage({ incognito: true })`.
3. Looks at every page it changed at **360, 390, 700 and 1280 px**, Ukrainian, light and dark, and reads the PNGs. `audit()` must report `scrollW == vw` and no new entries in `small`.
4. Records before / after heights for the pages in the §1 table that it owns.

Things that are easy to get wrong here: the taker's first page is already the test (identity fields on top, Submit at the bottom), there is no separate Start step for an open session; headless Edge follows the system theme, which is dark on this machine; a full-page capture shows sticky bars mid-page.

Tests to add or update: permissions and 404s for the new views (`delivery:pick`, `reports:attempt_void`, close confirmation), the submit-confirmation matrix (empty, partial, complete, past deadline, timer flag, unstarted first submit, class session), review with several rows, `?group=` handling, and one page-level offline / CSP check per new page in your `tests/test_offline_<name>.py` (no inline styles, scripts or `on*=` handlers).

## 9. Translations

Wrap every new string. Write the Ukrainian yourself into your fragment `locale/uk/parts/ux_<name>.po` (header as in `locale/uk/parts/manage.po`, three plural forms). Do not edit `locale/uk/LC_MESSAGES/django.po` and do not run `scripts/i18n.py`; the orchestrator extracts, merges, checks and compiles at the end. Texts used by JS travel in `data-` attributes.

Wording to keep consistent across workstreams:

| English `msgid` | Ukrainian |
|---|---|
| Open a session | Відкрити сесію |
| Open a session for this group | Відкрити сесію для цієї групи |
| You have answered %(done)s of %(total)s questions. | Ви відповіли на %(done)s із %(total)s запитань. |
| Submit anyway | Усе одно надіслати |
| Saved | Збережено |
| No connection. Your answers will be sent when it is back. | Немає з'єднання. Відповіді буде надіслано, щойно воно з'явиться. |
| 1 minute left | Залишилась 1 хвилина |
| Cancel attempt | Скасувати спробу |
| Close session | Закрити сесію |
| Presentation mode | Режим показу |
| Save and go to the next unreviewed attempt | Зберегти й перейти до наступної неперевіреної спроби |
| More | Ще |

("Attempt cancelled" and "Your teacher cancelled this attempt." already exist in `done.html`.)

## 10. Integration (orchestrator, after the workstreams report)

1. Full `pytest`, `ruff check .`, `ruff format --check .`, `manage.py check`.
2. `scripts/i18n.py extract`, `merge locale/uk/parts`, `check`, `compile`; commit `django.po` and `django.mo`.
3. One end-to-end pass on a single instance with `scripts/ui_shots.mjs`: teacher opens a class session from the dashboard, a student submits half-empty (sees the panel), the teacher cancels that attempt, the student retakes, the teacher closes the session with one student still working (sees the confirmation), reviews with "Save and next", reads the results on a phone.
4. Fill in the after-column of the §1 table in [log.md](../log.md), update README (navigation, cancel attempt, close confirmation), move the items on [BOARD.md](../BOARD.md).

## 11. Final report of each workstream (last message, under 40 lines)

What you built (files), which tasks are complete and which are not, decisions you took where this contract was silent, anything you had to work around in a frozen file, before / after heights, and what you verified live.
