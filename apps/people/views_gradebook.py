"""Group gradebook pages (KT-606): the matrix on screen and as CSV."""

from __future__ import annotations

import contextlib
import csv
import re

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.utils.http import content_disposition_header, urlencode
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET

from apps.assessments.models import Project
from apps.core.text import csv_safe
from apps.grading.scales import fmt_number

from .access import get_group_or_404
from .gradebook import OK_FROM, WARN_FROM, Gradebook, build_gradebook

_UNSAFE_FILENAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


def _filters(request, group):
    """(project, since) from the query string.

    The project must belong to the group's owner (a teacher's own projects): anything else is
    a 404, so ids of other teachers' projects are never confirmed. A malformed date or id is
    ignored, as if the filter were not set.
    """
    project = None
    raw = request.GET.get("project", "").strip()
    if raw.isdecimal():
        try:
            project = Project.objects.get(pk=int(raw), owner_id=group.owner_id)
        except Project.DoesNotExist:
            raise Http404 from None
    since = None
    with contextlib.suppress(ValueError):
        since = parse_date(request.GET.get("since", "").strip())
    return project, since


def _build(request, group):
    project, since = _filters(request, group)
    book = build_gradebook(group, project=project, since=since, viewer=request.user)
    return book, project, since


def _legend() -> list[tuple[str, str]]:
    ok, warn = int(OK_FROM), int(WARN_FROM)
    return [
        ("ok", _("%(n)s %% and above: good") % {"n": ok}),
        ("warn", _("%(low)s %% to below %(high)s %%: fair") % {"low": warn, "high": ok}),
        ("bad", _("below %(n)s %%: weak") % {"n": warn}),
    ]


@login_required
@require_GET
def gradebook(request, pk: int):
    group = get_group_or_404(request.user, pk)
    book, project, since = _build(request, group)
    params = {}
    if project:
        params["project"] = project.pk
    if since:
        params["since"] = since.isoformat()
    csv_url = reverse("people:gradebook_csv", args=[group.pk])
    if params:
        csv_url += "?" + urlencode(params)
    return render(
        request,
        "people/gradebook/gradebook.html",
        {
            "group": group,
            "book": book,
            "project": project,
            "since": since,
            "projects": Project.objects.filter(owner_id=group.owner_id).only("pk", "title"),
            "csv_url": csv_url,
            "student_count": len(book.rows),
            "session_count": len(book.columns),
            "legend": _legend(),
        },
    )


def _filename(group) -> str:
    name = _UNSAFE_FILENAME.sub("_", group.name).strip(" ._")[:80] or "group"
    return f"gradebook-{name}.csv"


def _number(value) -> str:
    return "" if value is None else fmt_number(value)


def gradebook_rows(book: Gradebook) -> list[list[str]]:
    """The matrix as CSV rows: header, one row per student, then the average (and a note)."""
    header = [csv_safe(_("Student"))]
    for col in book.columns:
        header.append(csv_safe(f"{col.title} ({col.date:%d.%m.%Y})"))
    header.append(csv_safe(_("Average")))
    rows = [header]
    for row in book.rows:
        line = [csv_safe(row.student.full_name)]
        for cell in row.cells:
            line.append(
                "" if cell is None else _number(cell.percent) + ("*" if cell.provisional else "")
            )
        line.append(
            _number(row.average) + ("*" if row.provisional and row.average is not None else "")
        )
        rows.append(line)
    footer = [csv_safe(_("Average"))]
    for col in book.columns:
        footer.append(
            _number(col.average) + ("*" if col.provisional and col.average is not None else "")
        )
    footer.append(
        _number(book.overall_average)
        + ("*" if book.overall_provisional and book.overall_average is not None else "")
    )
    rows.append(footer)
    if book.has_provisional:
        rows.append(
            [_("* Provisional: some answers still wait for review, so the number may change.")]
        )
    return rows


@login_required
@require_GET
def gradebook_csv(request, pk: int):
    group = get_group_or_404(request.user, pk)
    book, _project, _since = _build(request, group)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = content_disposition_header(True, _filename(group))
    response.write("﻿")  # BOM so Excel opens Cyrillic correctly
    writer = csv.writer(response)
    for line in gradebook_rows(book):
        writer.writerow(line)
    return response
