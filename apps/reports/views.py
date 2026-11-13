import csv
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import content_disposition_header
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.views.decorators.http import require_http_methods

from apps.core.text import csv_safe
from apps.delivery import services
from apps.delivery.models import Answer, Attempt, Sitting
from apps.grading.service import grade_attempt

from . import data, pdf

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

    sort_key, descending = sort.lstrip("-"), sort.startswith("-")
    columns = {}
    for key in ("name", "score", "time"):
        active = sort_key == key
        columns[key] = {
            "next": f"-{key}" if sort == key else key,
            "aria": ("descending" if descending else "ascending") if active else "",
            "arrow": ("↓" if descending else "↑") if active else "",
        }

    pending_attempt = next(
        (
            a
            for a in sorted(attempts, key=lambda a: (a.started_at, a.pk))
            if a.pending_reviews and a.status in data.FINISHED
        ),
        None,
    )
    shown = data.filter_and_sort(attempts, status, sort)
    return render(
        request,
        "reports/session.html",
        {
            "sitting": sitting,
            "test": test,
            "grading_enabled": (test.get("grading") or {}).get("enabled", True),
            "summary": data.summarize(attempts),
            "rows": [{"attempt": a, "name": data.taker_name(a)} for a in shown],
            "any_provisional": any(a.pending_reviews and a.score is not None for a in shown),
            "items": data.item_analysis(test, attempts),
            "status": status,
            "sort": sort,
            "columns": columns,
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


def _attempt_or_404(user, pk: int) -> Attempt:
    attempt = get_object_or_404(
        Attempt.objects.select_related("sitting__revision__assessment"), pk=pk
    )
    if not data.can_view_sitting(user, attempt.sitting):
        raise Http404
    return attempt


def _save_review(request, attempt: Attempt, rows: list[data.SheetRow]) -> tuple[int, dict]:
    """Save every reviewable row of the posted sheet. Returns (saved count, errors by question id).

    An empty points field leaves the answer as it is. A bad row is reported and does not stop
    the others; what the teacher typed is kept for the next render."""
    with transaction.atomic():  # a failing regrade must not leave scores stored but not counted
        return _save_review_rows(request, attempt, rows)


def _save_review_rows(request, attempt: Attempt, rows) -> tuple[int, dict]:
    saved = 0
    errors: dict[str, tuple[str, str, str]] = {}
    for row in rows:
        if not row.can_review or row.answer is None:
            continue
        qid = str(row.question["id"])
        raw = request.POST.get(f"points_{qid}", "").strip()
        comment = request.POST.get(f"comment_{qid}", "").strip()[:2000]
        if not raw:
            if comment and comment != (row.answer.feedback or ""):
                errors[qid] = (_("Enter points to save the comment."), raw, comment)
            continue
        points = _parse_points(raw, row.max_points)
        if points is None:
            message = _("Enter points from 0 to %(max)s in steps of 0.5.") % {
                "max": f"{row.max_points:f}"
            }
            errors[qid] = (message, raw, comment)
            continue
        row.answer.manual_score = points
        row.answer.feedback = comment
        row.answer.save(update_fields=["manual_score", "feedback"])
        saved += 1
    if saved:
        grade_attempt(attempt)
    return saved, errors


@login_required
@require_http_methods(["GET", "POST"])
def attempt_sheet(request, pk: int):
    attempt = _attempt_or_404(request.user, pk)
    sitting = attempt.sitting
    test = sitting.revision.test
    errors: dict[str, tuple[str, str, str]] = {}

    if request.method == "POST":
        rows = data.build_sheet(attempt, test, list(attempt.answers.all()))
        saved, errors = _save_review(request, attempt, rows)
        for row in rows:
            failed = errors.get(str(row.question["id"]))
            if failed:
                messages.error(
                    request,
                    _("Question %(n)s was not saved. %(reason)s")
                    % {"n": row.number, "reason": failed[0]},
                )
        if saved:
            messages.success(
                request,
                ngettext("%(n)s answer saved.", "%(n)s answers saved.", saved) % {"n": saved},
            )
        if not errors:
            if request.POST.get("action") == "next":
                following = data.next_unreviewed_attempt(attempt)
                if following is not None:
                    return redirect("reports:attempt", pk=following.pk)
                if attempt.pending_reviews:
                    messages.info(request, _("No other attempt waits for review."))
                else:
                    messages.success(request, _("Everything in this session is reviewed."))
                return redirect("reports:session", sitting_pk=sitting.pk)
            if not saved:
                messages.info(request, _("Nothing to save: no points were entered."))
            return redirect(request.path)

    rows = data.build_sheet(attempt, test, list(attempt.answers.all()))
    for row in rows:
        failed = errors.get(str(row.question["id"]))
        if failed:
            row.error, row.form_points, row.form_comment = failed
    return render(
        request,
        "reports/attempt.html",
        {
            "attempt": attempt,
            "sitting": sitting,
            "test": test,
            "name": data.taker_name(attempt),
            "taker_rows": _taker_rows(test, attempt),
            "rows": rows,
            "has_review": any(r.can_review for r in rows),
            "grading_enabled": (test.get("grading") or {}).get("enabled", True),
            "provisional": attempt.pending_reviews > 0,
            "voided": attempt.status == Attempt.Status.VOIDED,
            "next_attempt": data.next_unreviewed_attempt(attempt),
            "pdf_url": reverse("reports:attempt_pdf", args=[attempt.pk]),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def attempt_void(request, pk: int):
    """Cancel an attempt: a confirmation page first, then the POST. Same access as the sheet."""
    attempt = _attempt_or_404(request.user, pk)
    sitting = attempt.sitting
    name = data.taker_name(attempt)
    if attempt.status == Attempt.Status.VOIDED:
        messages.info(request, _("This attempt is already cancelled."))
        return redirect("reports:attempt", pk=attempt.pk)
    if request.method == "POST":
        services.void_attempt(attempt)
        messages.success(
            request, _("Attempt of %(name)s cancelled. It no longer counts.") % {"name": name}
        )
        return redirect("reports:session", sitting_pk=sitting.pk)
    test = sitting.revision.test
    return render(
        request,
        "reports/attempt_void.html",
        {
            "attempt": attempt,
            "sitting": sitting,
            "test": test,
            "name": name,
            "grading_enabled": (test.get("grading") or {}).get("enabled", True),
            "session_open": sitting.status == Sitting.Status.OPEN,
        },
    )


def _taker_rows(test: dict, attempt: Attempt) -> list[tuple[str, str]]:
    taker = attempt.taker or {}
    rows, seen = [], set()
    for field in test.get("taker_fields", []):
        key = field.get("key")
        seen.add(key)
        if key == "name":  # the name is the page heading
            continue
        rows.append((field.get("label") or key, str(taker.get(key, ""))))
    rows += [(k, str(v)) for k, v in taker.items() if k not in seen and k != "name"]
    return rows


def _csv_taker_fields(test: dict, attempts: list[Attempt]) -> list[dict]:
    """The taker columns of the CSV: the test's own fields, then a Name column if the test does
    not ask for one but people were identified by name (a class session stores the picked
    student's name), then any other key the attempts carry. Same rule as the PDF sheets."""
    fields = [dict(f) for f in test.get("taker_fields") or []]
    known = {f["key"] for f in fields}
    carried: list[str] = []
    for a in attempts:
        for key in a.taker or {}:
            if key not in known and key not in carried:
                carried.append(key)
    if "name" in carried:
        carried.remove("name")
        fields.insert(0, {"key": "name", "label": _("Name")})
    elif not fields:
        fields.append({"key": "name", "label": _("Name")})
    return fields + [{"key": key, "label": key} for key in carried]


@login_required
def session_csv(request, sitting_pk: int):
    sitting = _sitting_or_404(request.user, sitting_pk)
    test = sitting.revision.test
    questions = test.get("questions", [])
    attempts = list(sitting.attempts.all())
    fields = _csv_taker_fields(test, attempts)

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
            _("Status"),
            _("Started"),
            _("Submitted"),
            _("Score"),
            _("Max score"),
            _("Percent"),
            _("Grade"),
            _("Pending reviews"),
        ]
        + [f"{n}. {q['id']}" for n, q in enumerate(questions, start=1)]
    )
    for a in attempts:
        writer.writerow(
            [csv_safe((a.taker or {}).get(f["key"], "")) for f in fields]
            + [
                a.status,
                a.started_at.isoformat(timespec="seconds"),
                a.submitted_at.isoformat(timespec="seconds") if a.submitted_at else "",
                "" if a.score is None else a.score,
                "" if a.max_score is None else a.max_score,
                "" if a.percent is None else a.percent,
                csv_safe(a.grade),
                a.pending_reviews,
            ]
            + [
                "" if points.get((a.pk, str(q["id"]))) is None else points[(a.pk, str(q["id"]))]
                for q in questions
            ]
        )
    return response


def _pdf_response(content: bytes, filename: str) -> HttpResponse:
    response = HttpResponse(content, content_type="application/pdf")
    response["Content-Disposition"] = content_disposition_header(False, filename)
    return response


@login_required
def attempt_pdf(request, pk: int):
    attempt = get_object_or_404(
        Attempt.objects.select_related("sitting__revision__assessment").prefetch_related("answers"),
        pk=pk,
    )
    if not data.can_view_sitting(request.user, attempt.sitting):
        raise Http404
    options = pdf.PdfOptions.from_query(request.GET)
    return _pdf_response(pdf.render_pdf([attempt], options), pdf.attempt_filename(attempt))


@login_required
def session_pdf(request, sitting_pk: int):
    """All sheets of a session in one file. `status` picks the selection (default: finished)."""
    sitting = _sitting_or_404(request.user, sitting_pk)
    attempts = list(
        sitting.attempts.select_related("sitting__revision__assessment").prefetch_related("answers")
    )
    status = request.GET.get("status", "finished")
    if status not in data.STATUS_FILTERS:
        status = "finished"
    selected = data.filter_and_sort(attempts, status, "name")
    options = pdf.PdfOptions.from_query(request.GET)
    return _pdf_response(pdf.render_pdf(selected, options), pdf.session_filename(sitting))
