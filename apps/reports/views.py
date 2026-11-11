import csv
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods

from apps.delivery.models import Answer, Attempt, Sitting
from apps.grading.service import grade_attempt

from . import data

HALF = Decimal("0.5")


def _sitting_or_404(user, pk: int) -> Sitting:
    sitting = get_object_or_404(Sitting.objects.select_related("revision__assessment"), pk=pk)
    if not data.can_view_sitting(user, sitting):
        raise Http404
    return sitting


@login_required
def session_results(request, sitting_pk: int):
    sitting = _sitting_or_404(request.user, sitting_pk)
    test = sitting.revision.test
    attempts = list(sitting.attempts.all())

    status = request.GET.get("status", "all")
    if status not in data.STATUS_FILTERS:
        status = "all"
    sort = request.GET.get("sort", "time")
    if sort not in data.SORTS:
        sort = "time"

    next_sort = {}
    for key in ("name", "score", "time"):
        next_sort[key] = f"-{key}" if sort == key else key

    pending_attempt = next(
        (a for a in sorted(attempts, key=lambda a: (a.started_at, a.pk)) if a.pending_reviews), None
    )
    return render(
        request,
        "reports/session.html",
        {
            "sitting": sitting,
            "test": test,
            "grading_enabled": (test.get("grading") or {}).get("enabled", True),
            "summary": data.summarize(attempts),
            "rows": [
                {"attempt": a, "name": data.taker_name(a)}
                for a in data.filter_and_sort(attempts, status, sort)
            ],
            "items": data.item_analysis(test, attempts),
            "status": status,
            "sort": sort,
            "next_sort": next_sort,
            "status_filters": [
                ("all", _("All")),
                ("finished", _("Finished")),
                ("in_progress", _("In progress")),
                ("needs_review", _("Needs review")),
                ("voided", _("Voided")),
            ],
            "first_pending": pending_attempt,
        },
    )


def _parse_points(raw: str, max_points: Decimal) -> Decimal | None:
    try:
        points = Decimal((raw or "").strip().replace(",", "."))
    except InvalidOperation:
        return None
    if not points.is_finite() or points < 0 or points > max_points or points % HALF != 0:
        return None
    return points.quantize(Decimal("0.01"))


def _save_review(request, attempt: Attempt, test: dict):
    key = request.POST.get("question_key", "")
    question = next((q for q in test.get("questions", []) if str(q["id"]) == key), None)
    answer = Answer.objects.filter(attempt=attempt, question_key=key).first()
    if question is None or answer is None or answer.status not in data.REVIEWABLE:
        messages.error(request, _("This answer cannot be reviewed."))
        return
    max_points = Decimal(str(question.get("points", 1)))
    points = _parse_points(request.POST.get("points", ""), max_points)
    if points is None:
        messages.error(
            request,
            _("Enter points from 0 to %(max)s in steps of 0.5.") % {"max": f"{max_points:f}"},
        )
        return
    answer.manual_score = points
    answer.feedback = request.POST.get("comment", "").strip()[:2000]
    answer.save(update_fields=["manual_score", "feedback"])
    grade_attempt(attempt)
    messages.success(request, _("Saved."))


@login_required
@require_http_methods(["GET", "POST"])
def attempt_sheet(request, pk: int):
    attempt = get_object_or_404(
        Attempt.objects.select_related("sitting__revision__assessment"), pk=pk
    )
    sitting = attempt.sitting
    if not data.can_view_sitting(request.user, sitting):
        raise Http404
    test = sitting.revision.test

    if request.method == "POST":
        _save_review(request, attempt, test)
        key = request.POST.get("question_key", "")
        url = request.path + (f"#q-{key}" if key else "")
        return redirect(url)

    answers = list(attempt.answers.all())
    grading = test.get("grading") or {}
    return render(
        request,
        "reports/attempt.html",
        {
            "attempt": attempt,
            "sitting": sitting,
            "test": test,
            "name": data.taker_name(attempt),
            "taker_rows": _taker_rows(test, attempt),
            "rows": data.build_sheet(attempt, test, answers),
            "grading_enabled": grading.get("enabled", True),
            "provisional": attempt.pending_reviews > 0,
            "next_attempt": data.next_unreviewed_attempt(attempt),
        },
    )


def _taker_rows(test: dict, attempt: Attempt) -> list[tuple[str, str]]:
    taker = attempt.taker or {}
    rows, seen = [], set()
    for field in test.get("taker_fields", []):
        key = field.get("key")
        seen.add(key)
        rows.append((field.get("label") or key, str(taker.get(key, ""))))
    rows += [(k, str(v)) for k, v in taker.items() if k not in seen]
    return rows


def _csv_safe(value: object) -> str:
    """Neutralise spreadsheet formula injection in taker-supplied text."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@login_required
def session_csv(request, sitting_pk: int):
    sitting = _sitting_or_404(request.user, sitting_pk)
    test = sitting.revision.test
    questions = test.get("questions", [])
    fields = test.get("taker_fields") or [{"key": "name", "label": "Name"}]
    attempts = list(sitting.attempts.all())

    points: dict[tuple[int, str], Decimal | None] = {}
    for a in Answer.objects.filter(attempt__sitting=sitting):
        points[(a.attempt_id, a.question_key)] = a.points

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="results-{sitting.code}.csv"'
    response.write("﻿")  # BOM so Excel opens Cyrillic correctly
    writer = csv.writer(response)
    writer.writerow(
        [f.get("label") or f["key"] for f in fields]
        + [
            "Status",
            "Started",
            "Submitted",
            "Score",
            "Max score",
            "Percent",
            "Grade",
            "Pending reviews",
        ]
        + [f"{n}. {q['id']}" for n, q in enumerate(questions, start=1)]
    )
    for a in attempts:
        writer.writerow(
            [_csv_safe((a.taker or {}).get(f["key"], "")) for f in fields]
            + [
                a.status,
                a.started_at.isoformat(timespec="seconds"),
                a.submitted_at.isoformat(timespec="seconds") if a.submitted_at else "",
                "" if a.score is None else a.score,
                "" if a.max_score is None else a.max_score,
                "" if a.percent is None else a.percent,
                _csv_safe(a.grade),
                a.pending_reviews,
            ]
            + [
                "" if points.get((a.pk, str(q["id"]))) is None else points[(a.pk, str(q["id"]))]
                for q in questions
            ]
        )
    return response
