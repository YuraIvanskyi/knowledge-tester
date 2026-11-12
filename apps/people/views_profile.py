"""Student profile views (workstream D, KT-605): the page, notes, CSV, PDF and deletion.

Every view needs a login and goes through `get_student_or_404`, so a foreign student is a 404
and never leaks a name. Mutations are POST-only (CSRF is on for the whole site).
"""

from __future__ import annotations

import csv

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import content_disposition_header
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy, ngettext
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.reports.student_pdf import render_student_pdf

from . import profile as profile_data
from .access import get_student_or_404
from .profile import NOTES_MAX_LENGTH, csv_safe, download_name

KEEP, DELETE = "keep", "delete"


class NotesForm(forms.Form):
    notes = forms.CharField(
        label=gettext_lazy("Notes"),
        required=False,
        strip=True,
        max_length=NOTES_MAX_LENGTH,
        widget=forms.Textarea(attrs={"rows": 5}),
    )


def _back_url(student) -> str:
    if student.group_id:
        return reverse("people:group", args=[student.group_id])
    return reverse("people:students")


def _render_profile(request, student, form: NotesForm, status: int = 200):
    profile = profile_data.build_profile(student, viewer=request.user)
    return render(
        request,
        "people/profile/student.html",
        {
            "student": student,
            "profile": profile,
            "form": form,
            "not_counted": profile_data.not_counted_text(profile),
            "back_url": _back_url(student),
            "notes_limit": NOTES_MAX_LENGTH,
        },
        status=status,
    )


@login_required
@require_GET
def student_profile(request, pk: int):
    student = get_student_or_404(request.user, pk)
    return _render_profile(request, student, NotesForm(initial={"notes": student.notes}))


@login_required
@require_POST
def student_notes(request, pk: int):
    student = get_student_or_404(request.user, pk)
    data = request.POST.copy()
    data["notes"] = profile_data.normalize_text(data.get("notes", ""))
    form = NotesForm(data)
    if not form.is_valid():
        return _render_profile(request, student, form, status=400)
    student.notes = form.cleaned_data["notes"]
    student.save(update_fields=["notes", "updated_at"])
    messages.success(request, _("Notes saved."))
    return redirect(reverse("people:student", args=[student.pk]) + "#notes")


# --- delete ------------------------------------------------------------------------------------


@login_required
@require_http_methods(["GET", "HEAD", "POST"])
def student_delete(request, pk: int):
    student = get_student_or_404(request.user, pk)
    counts = profile_data.link_counts(student, request.user)

    if request.method == "POST":
        choice = request.POST.get("attempts")
        if choice not in (KEEP, DELETE):
            messages.error(request, _("Choose what happens to the attempts of this student."))
            return redirect("people:student_delete", pk=student.pk)
        name, back_url = student.full_name, _back_url(student)
        outcome = profile_data.delete_student(student, choice == DELETE, viewer=request.user)
        _flash_deleted(request, name, outcome)
        return redirect(back_url)

    return render(
        request,
        "people/profile/delete.html",
        {
            "student": student,
            "counts": counts,
            "back_url": reverse("people:student", args=[student.pk]),
            "KEEP": KEEP,
            "DELETE": DELETE,
        },
    )


def _flash_deleted(request, name: str, outcome: profile_data.DeleteOutcome) -> None:
    deleted, unlinked = outcome.deleted_attempts, outcome.unlinked_attempts
    if deleted:
        text = ngettext(
            "Student “%(name)s” and %(n)s attempt deleted.",
            "Student “%(name)s” and %(n)s attempts deleted.",
            deleted,
        )
        messages.success(request, text % {"name": name, "n": deleted})
        if unlinked:
            messages.info(
                request,
                ngettext(
                    "%(n)s attempt from a session of another teacher was only unlinked.",
                    "%(n)s attempts from sessions of another teacher were only unlinked.",
                    unlinked,
                )
                % {"n": unlinked},
            )
    elif unlinked:
        text = ngettext(
            "Student “%(name)s” deleted. %(n)s attempt stays in its session, unlinked.",
            "Student “%(name)s” deleted. %(n)s attempts stay in their sessions, unlinked.",
            unlinked,
        )
        messages.success(request, text % {"name": name, "n": unlinked})
    else:
        messages.success(request, _("Student “%(name)s” deleted.") % {"name": name})


# --- downloads ---------------------------------------------------------------------------------


@login_required
@require_GET
def student_csv(request, pk: int):
    student = get_student_or_404(request.user, pk)
    profile = profile_data.build_profile(student, viewer=request.user)
    group = student.group.name if student.group_id else ""

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = content_disposition_header(
        True, download_name(student, "csv")
    )
    response.write("﻿")  # BOM so Excel opens Cyrillic correctly
    writer = csv.writer(response)
    writer.writerow(
        [
            _("Student"),
            _("Group"),
            _("Test"),
            _("Project"),
            _("Session"),
            _("Session code"),
            _("Date"),
            _("Status"),
            _("Score"),
            _("Max score"),
            _("Percent"),
            _("Grade"),
            _("Pending reviews"),
        ]
    )
    for row in profile.all_rows:
        writer.writerow(
            [
                csv_safe(student.full_name),
                csv_safe(group),
                csv_safe(row.test_title),
                csv_safe(row.project_title),
                csv_safe(row.session_title),
                csv_safe(row.session_code),
                timezone.localtime(row.when).strftime("%Y-%m-%d %H:%M"),
                row.status,
                "" if row.score is None else row.score,
                "" if row.max_score is None else row.max_score,
                "" if row.percent is None else row.percent,
                csv_safe(row.grade),
                row.pending_reviews,
            ]
        )
    return response


@login_required
@require_GET
def student_pdf(request, pk: int):
    student = get_student_or_404(request.user, pk)
    profile = profile_data.build_profile(student, viewer=request.user)
    content = render_student_pdf(
        profile,
        paper=request.GET.get("paper", "A4"),
        not_counted=profile_data.not_counted_text(profile),
    )
    response = HttpResponse(content, content_type="application/pdf")
    response["Content-Disposition"] = content_disposition_header(
        True, download_name(student, "pdf")
    )
    return response
