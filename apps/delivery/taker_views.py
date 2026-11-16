"""Public taker flow (no login). Never expose correct answers before show_result allows it."""

import json
import uuid
from decimal import Decimal
from types import SimpleNamespace

from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods, require_POST

from apps.exchange import variants as test_variants

from . import roster, services
from .models import Attempt, Sitting

COOKIE_MAX_AGE = 60 * 60 * 24 * 3
FIELD_PREFIX = "tf_"
# Taker fields a class session never asks: the class is known from the session itself.
# `name` is replaced by the picked student; `class` / `group` are filled with the group's name.
GROUP_FIELD_KEYS = frozenset({"class", "group"})


# --- helpers -----------------------------------------------------------------------------------


def _get_sitting(code: str) -> Sitting:
    try:
        return Sitting.objects.select_related("revision", "group").get(
            code=services.normalize_code(code)
        )
    except Sitting.DoesNotExist:
        raise Http404 from None


def _cookie_name(sitting: Sitting) -> str:
    return f"kt_attempt_{sitting.code}"


def _get_attempt(request, sitting: Sitting) -> Attempt | None:
    raw = request.COOKIES.get(_cookie_name(sitting))
    if not raw:
        return None
    try:
        token = uuid.UUID(raw)
    except ValueError:
        return None
    attempt = Attempt.objects.filter(sitting=sitting, token=token).first()
    if attempt is not None:
        attempt.sitting = sitting  # already loaded with its revision: attempt.test needs both
    return attempt


def _attempt_of_page(request, sitting: Sitting, page_token) -> tuple[Attempt | None, bool]:
    """The attempt of this browser: its cookie, or else the attempt whose token the posting page
    carries (that token becomes the cookie, so it is the same secret). The fallback covers a
    request that leaves before the Set-Cookie of the first one has arrived. Returns
    (attempt or None, True when it was found by the page token and the cookie must be set)."""
    attempt = _get_attempt(request, sitting)
    if attempt is None and page_token is not None:
        attempt = Attempt.objects.filter(sitting=sitting, token=page_token).first()
        if attempt is not None:
            attempt.sitting = sitting
        return attempt, attempt is not None
    return attempt, False


def _set_cookie(response, sitting: Sitting, attempt: Attempt):
    response.set_cookie(
        _cookie_name(sitting),
        str(attempt.token),
        max_age=COOKIE_MAX_AGE,
        path="/s/",
        httponly=True,
        samesite="Lax",
    )
    return response


def _seconds_left(attempt: Attempt) -> int | None:
    if not attempt.deadline_at:
        return None
    return max(0, int((attempt.deadline_at - timezone.now()).total_seconds()))


def _max_attempts(test: dict) -> int:
    return (test.get("settings") or {}).get("max_attempts") or 1


def _answer_values(attempt: Attempt) -> dict[str, object]:
    return {a.question_key: a.value for a in attempt.answers.all() if a.value is not None}


def _build_questions(attempt: Attempt, test: dict, values: dict[str, object]) -> list[dict]:
    """Whitelist what the page may see: no correct flags, accepted answers or rubrics."""
    by_id = services.question_map(test)
    result = []
    for number, qid in enumerate((q for q in attempt.question_order if q in by_id), start=1):
        q = by_id[qid]
        item = {
            "id": qid,
            "number": number,
            "type": q["type"],
            "text": q["text"],
            "hint": q.get("hint", ""),
            "required": bool(q.get("required")),
            "n": q.get("n"),
            "value": values.get(qid),
            "is_choice": q["type"] in services.CHOICE_TYPES,
            "multi": q["type"] in ("multiple_choice", "choose_n"),
        }
        if item["is_choice"]:
            texts = {o["id"]: o["text"] for o in q.get("options", [])}
            picked = set(item["value"] or [])
            item["options"] = [
                {"id": oid, "text": texts[oid], "checked": oid in picked}
                for oid in attempt.option_orders.get(qid, [])
                if oid in texts
            ]
        result.append(item)
    return result


def _render_take(request, sitting, attempt, missing=None, unanswered=None):
    test = attempt.test
    questions = _build_questions(attempt, test, _answer_values(attempt))
    context = {
        "sitting": sitting,
        "test": test,
        "attempt": attempt,
        "questions": questions,
        "total": len(questions),
        "answered": sum(1 for q in questions if q["value"] is not None),
        "seconds_left": _seconds_left(attempt),
        "variant_label": attempt.variant_label,
        "missing": missing or [],
        "unanswered": unanswered or [],
    }
    return render(request, "delivery/take.html", context)


def _parse_token(raw) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError, AttributeError):
        return None


def _skipped_in_group(key: str) -> bool:
    return key == "name" or str(key).strip().casefold() in GROUP_FIELD_KEYS


def _identity_context(sitting, test, data) -> dict:
    """Who-are-you part of the landing page, shared by the test page and the Start form.

    Free-name sessions ask the typed fields as before. Group-bound sessions replace the typed
    `name` field by the class list (names only, see apps.delivery.roster) and, with a PIN, ask
    for it; a `class` / `group` field is not asked either (the group's name is stored instead);
    every other taker field is still asked. `data` is what was posted (or {})."""
    group_mode = roster.is_group_bound(sitting)
    fields = [
        {**f, "value": data.get(FIELD_PREFIX + f["key"], "")}
        for f in services.taker_fields(test)
        if not (group_mode and _skipped_in_group(f["key"]))
    ]
    context = {"fields": fields, "group_mode": group_mode}
    if group_mode:
        context.update(
            roster=roster.picker_options(sitting),
            picked=roster.parse_student_id(data.get("student")),
            pin_mode=sitting.use_pin,
        )
    return context


def _render_unstarted(
    request,
    sitting,
    test,
    errors=None,
    data=None,
    token=None,
    preview=None,
    cancelled=False,
    variant=None,
):
    """The test itself as the landing page: identity fields on top, questions below.
    The attempt is created on the first autosave or on submit, using this page's token.
    The token also decides the variant, so the attempt gets the questions shown here.
    `variant` forces one (teacher preview only)."""
    data = data if data is not None else {}
    full_test = test
    token = token or services.new_token(sitting, full_test)
    variant_id = variant or test_variants.for_token(full_test, token)
    test = test_variants.view(full_test, variant_id)
    order, option_orders = services.shuffled_orders(test, str(token))
    stub = SimpleNamespace(question_order=order, option_orders=option_orders)
    getlist = data.getlist if hasattr(data, "getlist") else lambda key: []
    values = {}
    for qid, q in services.question_map(test).items():
        raw = getlist(f"q_{qid}") if q["type"] in services.CHOICE_TYPES else data.get(f"q_{qid}")
        values[qid] = services.clean_value(q, raw)
    questions = _build_questions(stub, test, values)
    context = {
        **_identity_context(sitting, test, data),
        "sitting": sitting,
        "test": test,
        "unstarted": True,
        "token": token,
        "errors": errors or [],
        "questions": questions,
        "total": len(questions),
        "answered": sum(1 for q in questions if q["value"] is not None),
        "seconds_left": None,
        "time_limit": services.time_limit_minutes(test),  # clock starts with the attempt
        "variant_label": test_variants.label(full_test, variant_id),
        "missing": [],
        "unanswered": [],
        "preview": preview,
        "cancelled": cancelled,
    }
    return render(request, "delivery/take.html", context)


def render_preview(request, test: dict, preview: dict):
    """The test page exactly as a taker sees it, for a teacher. Nothing is stored.

    `preview` = {"url": where the form posts back to, "back_url": link back to the editor}.
    Posting only re-renders the page with the answers kept.
    """
    posted = request.POST if request.method == "POST" else None
    token = _parse_token(posted.get("attempt_token")) if posted is not None else None
    return _render_unstarted(
        request,
        None,
        test,
        data=posted,
        token=token,
        preview=preview,
        variant=preview.get("variant"),
    )


# --- entering and starting ---------------------------------------------------------------------


@require_http_methods(["GET", "POST"])
def enter(request):
    if request.method != "POST":
        return redirect("core:landing")
    raw = request.POST.get("code", "")
    code = services.normalize_code(raw)
    if code and Sitting.objects.filter(code=code).exists():
        return redirect("taker:session", code=code)
    return render(request, "delivery/enter_error.html", {"entered": raw.strip()[:12]})


def _start_errors(data, sitting: Sitting, test: dict, fields: list[dict]):
    """Validate identity fields + access code from a QueryDict or plain dict.

    The one place every way of starting an attempt goes through (Start form, first autosave,
    first submit). Returns (errors, taker values, picked student or None). In a group-bound
    session the student comes from the class list (never a typed name), the PIN is checked when
    required, and `max_attempts` is counted per student."""
    errors, taker = [], {}
    group_mode = roster.is_group_bound(sitting)
    if sitting.access_code and (
        (data.get("access_code") or "").strip().casefold() != sitting.access_code.strip().casefold()
    ):
        errors.append(_("The access code is not correct."))
    for field in fields:
        if group_mode and field["key"] == "name":
            continue  # the picked student's name is used instead
        if group_mode and _skipped_in_group(field["key"]):
            taker[field["key"]] = sitting.group.name  # known from the session, not asked
            continue
        value = " ".join(str(data.get(FIELD_PREFIX + field["key"]) or "").split())[:200]
        if field.get("required", False) and not value:
            errors.append(_("Please fill in: %(field)s.") % {"field": field["label"]})
        taker[field["key"]] = value
    if group_mode:
        student = None
        if not errors:  # the PIN is only compared (and counted) once everything else is fine
            entry = roster.check_entry(sitting, data, max_attempts=_max_attempts(test))
            student, errors = entry.student, entry.errors
        elif roster.find_student(sitting, data.get("student")) is None:
            errors.append(_("Please choose your name from the list."))
        if student is not None:
            taker = {"name": student.full_name, **taker}
        return errors, taker, (student if not errors else None)
    used = services.attempts_used(sitting, taker.get("name", ""))
    if not errors and used >= _max_attempts(test):
        errors.append(_("You have already taken this test."))
    return errors, taker, None


def session(request, code: str):
    sitting = _get_sitting(code)
    test = sitting.revision.test
    attempt = _get_attempt(request, sitting)
    closed = sitting.status == Sitting.Status.CLOSED
    cancelled = False

    if attempt is not None and attempt.status == Attempt.Status.VOIDED and not closed:
        # The teacher cancelled the previous attempt: it never blocks a new one.
        attempt, cancelled = None, True

    if attempt is not None:
        services.enforce_deadline(attempt)
        if not attempt.is_finished:
            return redirect("taker:take", code=sitting.code)
        # In a class session the identity is the picked student, not the browser: the next
        # student at a shared computer must be able to pick their own name.
        one_try = _max_attempts(test) <= 1 and not roster.is_group_bound(sitting)
        if closed or one_try:
            return redirect("taker:done", code=sitting.code)

    fields = services.taker_fields(test)
    posted = request.POST if request.method == "POST" else {}
    context = {
        **_identity_context(sitting, test, posted),
        "sitting": sitting,
        "test": test,
        "question_count": test_variants.question_count(test),
        "time_limit": services.time_limit_minutes(test),
        "closed": closed,
        "previous": attempt,
        "cancelled": cancelled,
    }
    if not closed and request.method != "POST" and not sitting.access_code:
        return _render_unstarted(request, sitting, test, cancelled=cancelled)
    # With an access code the questions stay hidden until it has been entered: the Start form
    # below (identity + code, no questions) is the landing page, and posting it starts the attempt.
    if closed or request.method != "POST":
        return render(request, "delivery/session.html", context)

    errors, taker, student = _start_errors(request.POST, sitting, test, fields)
    if errors:
        context["errors"] = errors
        return render(request, "delivery/session.html", context)
    new_attempt = services.start_attempt(sitting, taker, student=student)
    return _set_cookie(redirect("taker:take", code=sitting.code), sitting, new_attempt)


# --- taking ------------------------------------------------------------------------------------


def take(request, code: str):
    sitting = _get_sitting(code)
    attempt = _get_attempt(request, sitting)
    if attempt is None:
        return redirect("taker:session", code=sitting.code)
    if services.enforce_deadline(attempt) or attempt.is_finished:
        return redirect("taker:done", code=sitting.code)
    return _render_take(request, sitting, attempt)


@require_POST
def save(request, code: str):
    """Autosave endpoint: JSON {"answers": {question_id: value}}. Never required for submit.
    Before the attempt exists (the test page is the landing page), a payload with
    "unstarted": true plus the tf_* fields starts it as soon as the details are valid."""
    sitting = _get_sitting(code)
    try:
        payload = json.loads(request.body or b"{}")
        answers = payload["answers"]
        if not isinstance(answers, dict):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        return JsonResponse({"error": "bad request"}, status=400)
    attempt, created = _attempt_of_page(
        request, sitting, _parse_token(payload.get("attempt_token"))
    )

    if attempt is None or (attempt.is_finished and payload.get("unstarted")):
        if not payload.get("unstarted") or sitting.status == Sitting.Status.CLOSED:
            return JsonResponse({"error": "no attempt"}, status=403)
        test = sitting.revision.test
        errors, taker, student = _start_errors(payload, sitting, test, services.taker_fields(test))
        if errors:
            return JsonResponse({"started": False, "errors": errors})
        attempt = services.start_attempt(
            sitting, taker, token=_parse_token(payload.get("attempt_token")), student=student
        )
        created = True

    if not attempt.is_finished and services.is_past_deadline(attempt, services.SUBMIT_GRACE):
        services.finalize(attempt, Attempt.Status.AUTO_SUBMITTED)
    if attempt.is_finished:
        url = reverse("taker:done", kwargs={"code": sitting.code})
        return JsonResponse({"done": True, "url": url}, status=409)
    services.save_answers(attempt, attempt.test, answers)
    response = JsonResponse(
        {
            "done": False,
            "started": True,
            "answered": len(services.answered_ids(attempt)),
            "left": _seconds_left(attempt),
        }
    )
    return _set_cookie(response, sitting, attempt) if created else response


def _posted_values(request, test: dict) -> dict[str, object]:
    values = {}
    for q in test.get("questions", []):
        key = f"q_{q['id']}"
        if q["type"] in services.CHOICE_TYPES:
            values[q["id"]] = request.POST.getlist(key)
        else:
            values[q["id"]] = request.POST.get(key, "")
    return values


@require_POST
def submit(request, code: str):
    sitting = _get_sitting(code)
    test = sitting.revision.test
    token = _parse_token(request.POST.get("attempt_token"))
    attempt, created = _attempt_of_page(request, sitting, token)

    if attempt is not None and token is not None and attempt.token == token:
        pass  # the attempt shown on this page (autosave started it, or a repeated submit)
    elif attempt is None or attempt.is_finished:
        if attempt is not None and not request.POST.get("unstarted"):
            return redirect("taker:done", code=sitting.code)  # repeated submit: idempotent
        if attempt is not None and sitting.status == Sitting.Status.CLOSED:
            return redirect("taker:done", code=sitting.code)
        if not request.POST.get("unstarted") or sitting.status == Sitting.Status.CLOSED:
            return redirect("taker:session", code=sitting.code)
        errors, taker, student = _start_errors(
            request.POST, sitting, test, services.taker_fields(test)
        )
        if errors:
            return _render_unstarted(
                request, sitting, test, errors=errors, data=request.POST, token=token
            )
        attempt = services.start_attempt(sitting, taker, token=token, student=student)
        created = True

    def reply(response):
        return _set_cookie(response, sitting, attempt) if created else response

    if attempt.is_finished:
        return reply(redirect("taker:done", code=sitting.code))

    test = attempt.test  # from here on: this taker's variant
    within_grace = not services.is_past_deadline(attempt, services.SUBMIT_GRACE)
    # Only overwrite autosaved answers when the full form was actually posted.
    if request.POST.get("form_sent") and within_grace:
        services.save_answers(attempt, test, _posted_values(request, test))

    if services.is_past_deadline(attempt):
        services.finalize(attempt, Attempt.Status.AUTO_SUBMITTED)
        return reply(redirect("taker:done", code=sitting.code))

    answered = services.answered_ids(attempt)
    questions = _build_questions(attempt, test, {})
    missing = [q for q in questions if q["required"] and q["id"] not in answered]
    if missing:
        return reply(_render_take(request, sitting, attempt, missing=missing))

    # Ask once before finishing with questions left empty. The deadline branch above and the
    # timer's automatic submit (which posts confirm_unanswered=1) never ask.
    unanswered = [q for q in questions if q["id"] not in answered]
    if unanswered and not request.POST.get("confirm_unanswered"):
        return reply(_render_take(request, sitting, attempt, unanswered=unanswered))

    services.finalize(attempt, Attempt.Status.SUBMITTED)
    return reply(redirect("taker:done", code=sitting.code))


# --- done --------------------------------------------------------------------------------------


def _verdict(answer, question: dict) -> tuple[str, str]:
    """(css class, label) for the per-question line on the full result page."""
    if answer is None or answer.value is None:
        return "status-warn", _("Not answered")
    points = answer.points
    if answer.status == "needs_review" or points is None:
        return "status-warn", _("Awaiting review")
    if points >= Decimal(str(question.get("points", 1))):
        return "status-ok", _("Correct")
    if points <= 0:
        return "status-bad", _("Incorrect")
    return "status-warn", _("Partly correct")


def _full_review(attempt: Attempt, test: dict) -> list[dict]:
    answers = {a.question_key: a for a in attempt.answers.all()}
    by_id = services.question_map(test)
    rows = []
    for number, qid in enumerate((q for q in attempt.question_order if q in by_id), start=1):
        q = by_id[qid]
        answer = answers.get(qid)
        css, label = _verdict(answer, q)
        row = {
            "number": number,
            "text": q["text"],
            "css": css,
            "verdict": label,
            "points": answer.points if answer else None,
            "max_points": q.get("points", 1),
            "open": q["type"] == "open",
        }
        if q["type"] in services.CHOICE_TYPES:
            texts = {o["id"]: o["text"] for o in q.get("options", [])}
            picked = (answer.value if answer else None) or []
            row["given"] = [texts[o] for o in picked if o in texts]
            row["correct"] = [o["text"] for o in q.get("options", []) if o.get("correct")]
        else:
            row["given"] = [answer.value] if answer and answer.value else []
            row["correct"] = (
                [str(a) for a in q.get("accept", [])] if q["type"] == "short_answer" else []
            )
        rows.append(row)
    return rows


def done(request, code: str):
    sitting = _get_sitting(code)
    attempt = _get_attempt(request, sitting)
    if attempt is None:
        return redirect("taker:session", code=sitting.code)
    if not attempt.is_finished and not services.enforce_deadline(attempt):
        return redirect("taker:take", code=sitting.code)
    test = attempt.test
    show = (test.get("settings") or {}).get("show_result", "score")
    voided = attempt.status == Attempt.Status.VOIDED
    context = {
        "sitting": sitting,
        "test": test,
        "attempt": attempt,
        "voided": voided,
        "auto": attempt.status == Attempt.Status.AUTO_SUBMITTED,
        "variant_label": attempt.variant_label,
        "show_score": show in ("score", "full") and attempt.score is not None and not voided,
        "review": _full_review(attempt, test) if show == "full" and not voided else [],
        "can_retry": (voided or _max_attempts(test) > 1) and sitting.status == Sitting.Status.OPEN,
    }
    return render(request, "delivery/done.html", context)
