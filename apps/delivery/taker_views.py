"""Public taker flow (no login). Never expose correct answers before show_result allows it."""

import json
import uuid
from decimal import Decimal

from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods, require_POST

from . import services
from .models import Attempt, Sitting

COOKIE_MAX_AGE = 60 * 60 * 24 * 3
FIELD_PREFIX = "tf_"


# --- helpers -----------------------------------------------------------------------------------


def _get_sitting(code: str) -> Sitting:
    try:
        return Sitting.objects.select_related("revision").get(code=services.normalize_code(code))
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
    return Attempt.objects.filter(sitting=sitting, token=token).first()


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


def _render_take(request, sitting, attempt, missing=None):
    test = sitting.revision.test
    questions = _build_questions(attempt, test, _answer_values(attempt))
    context = {
        "sitting": sitting,
        "test": test,
        "attempt": attempt,
        "questions": questions,
        "total": len(questions),
        "answered": sum(1 for q in questions if q["value"] is not None),
        "seconds_left": _seconds_left(attempt),
        "missing": missing or [],
    }
    return render(request, "delivery/take.html", context)


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


def _start_errors(request, sitting: Sitting, test: dict, fields: list[dict]):
    errors, taker = [], {}
    if sitting.access_code and (
        request.POST.get("access_code", "").strip().casefold()
        != sitting.access_code.strip().casefold()
    ):
        errors.append(_("The access code is not correct."))
    for field in fields:
        value = " ".join(request.POST.get(FIELD_PREFIX + field["key"], "").split())[:200]
        if field.get("required", False) and not value:
            errors.append(_("Please fill in: %(field)s.") % {"field": field["label"]})
        taker[field["key"]] = value
    used = services.attempts_used(sitting, taker.get("name", ""))
    if not errors and used >= _max_attempts(test):
        errors.append(_("You have already taken this test."))
    return errors, taker


def session(request, code: str):
    sitting = _get_sitting(code)
    test = sitting.revision.test
    attempt = _get_attempt(request, sitting)
    closed = sitting.status == Sitting.Status.CLOSED

    if attempt is not None:
        services.enforce_deadline(attempt)
        if not attempt.is_finished:
            return redirect("taker:take", code=sitting.code)
        if closed or _max_attempts(test) <= 1:
            return redirect("taker:done", code=sitting.code)

    fields = services.taker_fields(test)
    posted = request.POST if request.method == "POST" else {}
    context = {
        "sitting": sitting,
        "test": test,
        "fields": [{**f, "value": posted.get(FIELD_PREFIX + f["key"], "")} for f in fields],
        "question_count": len(test.get("questions", [])),
        "time_limit": services.time_limit_minutes(test),
        "closed": closed,
        "previous": attempt,
    }
    if closed or request.method != "POST":
        return render(request, "delivery/session.html", context)

    errors, taker = _start_errors(request, sitting, test, fields)
    if errors:
        context["errors"] = errors
        return render(request, "delivery/session.html", context)
    new_attempt = services.start_attempt(sitting, taker)
    return _set_cookie(redirect("taker:take", code=sitting.code), sitting, new_attempt)


# --- taking ------------------------------------------------------------------------------------


def take(request, code: str):
    sitting = _get_sitting(code)
    attempt = _get_attempt(request, sitting)
    if attempt is None:
        return redirect("taker:session", code=sitting.code)
    if services.enforce_deadline(attempt):
        return redirect("taker:done", code=sitting.code)
    return _render_take(request, sitting, attempt)


@require_POST
def save(request, code: str):
    """Autosave endpoint: JSON {"answers": {question_id: value}}. Never required for submit."""
    sitting = _get_sitting(code)
    attempt = _get_attempt(request, sitting)
    if attempt is None:
        return JsonResponse({"error": "no attempt"}, status=403)
    if not attempt.is_finished and services.is_past_deadline(attempt, services.SUBMIT_GRACE):
        services.finalize(attempt, Attempt.Status.AUTO_SUBMITTED)
    if attempt.is_finished:
        url = reverse("taker:done", kwargs={"code": sitting.code})
        return JsonResponse({"done": True, "url": url}, status=409)
    try:
        answers = json.loads(request.body or b"{}")["answers"]
        if not isinstance(answers, dict):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        return JsonResponse({"error": "bad request"}, status=400)
    services.save_answers(attempt, sitting.revision.test, answers)
    return JsonResponse(
        {
            "done": False,
            "answered": len(services.answered_ids(attempt)),
            "left": _seconds_left(attempt),
        }
    )


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
    attempt = _get_attempt(request, sitting)
    if attempt is None:
        return redirect("taker:session", code=sitting.code)
    if attempt.is_finished:
        return redirect("taker:done", code=sitting.code)

    test = sitting.revision.test
    within_grace = not services.is_past_deadline(attempt, services.SUBMIT_GRACE)
    # Only overwrite autosaved answers when the full form was actually posted.
    if request.POST.get("form_sent") and within_grace:
        services.save_answers(attempt, test, _posted_values(request, test))

    if services.is_past_deadline(attempt):
        services.finalize(attempt, Attempt.Status.AUTO_SUBMITTED)
        return redirect("taker:done", code=sitting.code)

    answered = services.answered_ids(attempt)
    missing = [
        q for q in _build_questions(attempt, test, {}) if q["required"] and q["id"] not in answered
    ]
    if missing:
        return _render_take(request, sitting, attempt, missing=missing)

    services.finalize(attempt, Attempt.Status.SUBMITTED)
    return redirect("taker:done", code=sitting.code)


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
    test = sitting.revision.test
    show = (test.get("settings") or {}).get("show_result", "score")
    voided = attempt.status == Attempt.Status.VOIDED
    context = {
        "sitting": sitting,
        "test": test,
        "attempt": attempt,
        "voided": voided,
        "auto": attempt.status == Attempt.Status.AUTO_SUBMITTED,
        "show_score": show in ("score", "full") and attempt.score is not None and not voided,
        "review": _full_review(attempt, test) if show == "full" and not voided else [],
        "can_retry": _max_attempts(test) > 1 and sitting.status == Sitting.Status.OPEN,
    }
    return render(request, "delivery/done.html", context)
