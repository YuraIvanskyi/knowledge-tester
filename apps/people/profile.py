"""Student profile data (plan §14, KT-605): history, averages, CSV rows, deletion.

What counts for a student (people-contracts.md): an attempt linked to the student with status
`submitted` / `auto_submitted` and a score; `voided` never counts; an attempt that still has
`pending_reviews > 0` counts but is *provisional*, and so is every average that includes it.

Whose attempts are shown: only attempts of sessions created by the student's owner. The link is
owner-checked when it is made (delivery:link), but an admin may link across teachers, and a
teacher must never read another teacher's session through their own student. So everyone gets
the owner-only view, except an admin viewer, who sees everything that is linked. The same
rule decides which attempts "delete the student and their attempts" removes; any other linked
attempt is only unlinked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from django.db import transaction
from django.db.models import QuerySet
from django.db.models.fields.json import KT
from django.utils.text import slugify
from django.utils.translation import gettext, ngettext

from apps.delivery.models import Attempt

from .gradebook import mean
from .models import Student

COUNTED_STATUSES = (Attempt.Status.SUBMITTED, Attempt.Status.AUTO_SUBMITTED)
ONE_DECIMAL = Decimal("0.1")

# Row kinds. Only COUNTED rows feed the averages.
COUNTED = "counted"
IN_PROGRESS = "in_progress"
VOIDED = "voided"
NOT_GRADED = "not_graded"  # finished, but the test has grading switched off (no score)

NOTES_MAX_LENGTH = 2000


# ---------------------------------------------------------------------------------------------
# Querying
# ---------------------------------------------------------------------------------------------


def attempts_of(student: Student, viewer=None) -> QuerySet[Attempt]:
    """The attempts linked to `student` that `viewer` may see (see the module docstring)."""
    queryset = Attempt.objects.filter(student=student)
    if viewer is None or not viewer.is_admin_role:
        queryset = queryset.filter(sitting__created_by_id=student.owner_id)
    return queryset


def _history_queryset(student: Student, viewer=None) -> QuerySet[Attempt]:
    """Everything the profile shows in one query; the big JSON documents stay on disk."""
    return (
        attempts_of(student, viewer)
        .select_related("sitting__revision__assessment__project")
        .defer(
            "taker",
            "question_order",
            "option_orders",
            "sitting__revision__document",
            "sitting__revision__assessment__document",
        )
        .annotate(doc_title=KT("sitting__revision__document__test__title"))
    )


# ---------------------------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class HistoryRow:
    attempt_id: int
    kind: str
    status: str  # the raw Attempt.status
    when: datetime
    test_title: str
    project_id: int
    project_title: str
    session_id: int
    session_title: str
    session_code: str
    score: Decimal | None
    max_score: Decimal | None
    percent: Decimal | None
    grade: str
    pending_reviews: int

    @property
    def provisional(self) -> bool:
        return self.kind == COUNTED and self.pending_reviews > 0


@dataclass(frozen=True)
class ProjectStats:
    project_id: int
    title: str
    count: int  # counted attempts with a percent
    mean: Decimal | None
    best: Decimal | None
    latest: Decimal | None
    provisional: bool


@dataclass
class Profile:
    student: Student
    rows: list[HistoryRow] = field(default_factory=list)  # counted, newest first
    others: list[HistoryRow] = field(default_factory=list)  # not counted, newest first
    projects: list[ProjectStats] = field(default_factory=list)
    overall_mean: Decimal | None = None
    overall_count: int = 0
    provisional_attempts: int = 0  # counted attempts that still wait for a review
    in_progress: int = 0
    voided: int = 0
    not_graded: int = 0

    @property
    def provisional(self) -> bool:
        return self.provisional_attempts > 0

    @property
    def all_rows(self) -> list[HistoryRow]:
        """Counted and not counted rows together, newest first."""
        return sorted(self.rows + self.others, key=_newest_first, reverse=True)

    @property
    def others_count(self) -> int:
        return len(self.others)


def _newest_first(row: HistoryRow):
    return (row.when, row.attempt_id)


def _kind(attempt: Attempt) -> str:
    if attempt.status == Attempt.Status.VOIDED:
        return VOIDED
    if attempt.status == Attempt.Status.IN_PROGRESS:
        return IN_PROGRESS
    if attempt.score is None:
        return NOT_GRADED
    return COUNTED


def _row(attempt: Attempt) -> HistoryRow:
    sitting = attempt.sitting
    assessment = sitting.revision.assessment
    return HistoryRow(
        attempt_id=attempt.pk,
        kind=_kind(attempt),
        status=attempt.status,
        when=attempt.submitted_at or attempt.started_at,
        test_title=attempt.doc_title or assessment.title,
        project_id=assessment.project_id,
        project_title=assessment.project.title,
        session_id=sitting.pk,
        session_title=sitting.title,
        session_code=sitting.code,
        score=attempt.score,
        max_score=attempt.max_score,
        percent=attempt.percent,
        grade=attempt.grade,
        pending_reviews=attempt.pending_reviews,
    )


def project_stats(rows: list[HistoryRow]) -> list[ProjectStats]:
    """Per project: mean of percent, attempts, best, latest. `rows` are counted, newest first.

    A counted attempt without a percent (a test whose questions are all worth 0 points) is
    listed in the history but cannot be averaged, so it is left out of these numbers."""
    by_project: dict[int, list[HistoryRow]] = {}
    for row in rows:
        by_project.setdefault(row.project_id, []).append(row)
    stats = []
    for project_id, group in by_project.items():
        scored = [row for row in group if row.percent is not None]
        if not scored:
            continue
        percents = [row.percent for row in scored]
        stats.append(
            ProjectStats(
                project_id=project_id,
                title=group[0].project_title,
                count=len(scored),
                mean=mean(percents),
                best=max(percents),
                latest=scored[0].percent,
                provisional=any(row.provisional for row in scored),
            )
        )
    return sorted(stats, key=lambda s: (s.title.casefold(), s.project_id))


def profile_from_rows(student: Student, rows: list[HistoryRow]) -> Profile:
    """Sort the rows into counted / not counted and compute the averages (no database)."""
    profile = Profile(student=student)
    for row in sorted(rows, key=_newest_first, reverse=True):
        if row.kind == COUNTED:
            profile.rows.append(row)
        else:
            profile.others.append(row)
            if row.kind == IN_PROGRESS:
                profile.in_progress += 1
            elif row.kind == VOIDED:
                profile.voided += 1
            else:
                profile.not_graded += 1
    profile.provisional_attempts = sum(1 for row in profile.rows if row.provisional)
    profile.projects = project_stats(profile.rows)
    overall = [row.percent for row in profile.rows if row.percent is not None]
    profile.overall_count = len(overall)
    profile.overall_mean = mean(overall)
    return profile


def build_profile(student: Student, *, viewer=None) -> Profile:
    """Everything the profile page, the CSV and the PDF show. One query for the attempts."""
    return profile_from_rows(student, [_row(a) for a in _history_queryset(student, viewer)])


# ---------------------------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------------------------


def download_name(student: Student, extension: str) -> str:
    """File name from the student's name (Cyrillic kept; the view sends it as filename*)."""
    slug = slugify(student.full_name, allow_unicode=True) or f"student-{student.pk}"
    return f"{slug[:80]}_results.{extension}"


def normalize_text(value: str) -> str:
    """Browsers post line breaks as CRLF; store LF so a length limit counts them once."""
    return re.sub(r"\r\n?", "\n", value or "")


# ---------------------------------------------------------------------------------------------
# Deleting a student
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class LinkCounts:
    linked: int  # every attempt linked to the student, whatever its owner or status
    removable: int  # the ones "delete the attempts too" would remove (viewer's view)


def link_counts(student: Student, viewer=None) -> LinkCounts:
    return LinkCounts(
        linked=Attempt.objects.filter(student=student).count(),
        removable=attempts_of(student, viewer).count(),
    )


@dataclass(frozen=True)
class DeleteOutcome:
    deleted_attempts: int
    unlinked_attempts: int


@transaction.atomic
def delete_student(student: Student, delete_attempts: bool, *, viewer=None) -> DeleteOutcome:
    """Delete a student in one transaction.

    `delete_attempts=False`: their attempts stay in their sessions with the student link
    cleared (Attempt.taker, what was typed, is untouched). `True`: the attempts the viewer may
    see (see the module docstring) are deleted with their answers; anything else is unlinked."""
    linked = Attempt.objects.filter(student=student).count()
    deleted = 0
    if delete_attempts:
        ids = list(attempts_of(student, viewer).values_list("pk", flat=True))
        if ids:
            Attempt.objects.filter(pk__in=ids).delete()
        deleted = len(ids)
    student.delete()
    return DeleteOutcome(deleted_attempts=deleted, unlinked_attempts=linked - deleted)


def not_counted_text(profile: Profile) -> str:
    """'Not counted: 1 attempt in progress; 2 voided attempts' (empty when nothing is left out).
    Shared by the page and the PDF."""
    parts = []
    if profile.in_progress:
        parts.append(
            ngettext(
                "%(n)s attempt in progress",
                "%(n)s attempts in progress",
                profile.in_progress,
            )
            % {"n": profile.in_progress}
        )
    if profile.voided:
        parts.append(
            ngettext("%(n)s voided attempt", "%(n)s voided attempts", profile.voided)
            % {"n": profile.voided}
        )
    if profile.not_graded:
        parts.append(
            ngettext(
                "%(n)s attempt without a score",
                "%(n)s attempts without a score",
                profile.not_graded,
            )
            % {"n": profile.not_graded}
        )
    if not parts:
        return ""
    return gettext("Not counted: %(parts)s") % {"parts": "; ".join(parts)}
