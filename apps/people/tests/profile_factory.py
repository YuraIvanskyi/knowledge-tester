"""Row builders for the profile tests (workstream D). Plain ORM, no views, no grading."""

from __future__ import annotations

import itertools
from datetime import datetime, timedelta
from decimal import Decimal

from django.utils import timezone

from apps.assessments.models import Assessment, Project, Revision
from apps.delivery.models import Attempt, Sitting
from apps.people.models import Group, Student

_codes = itertools.count(1)
BASE_TIME = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.get_fixed_timezone(0))


def make_group(owner, name="7-А") -> Group:
    return Group.objects.create(owner=owner, name=name)


def make_student(owner, name="Іваненко Петро", group=None, **extra) -> Student:
    return Student.objects.create(owner=owner, full_name=name, group=group, **extra)


def make_project(owner, title="Математика") -> Project:
    return Project.objects.create(owner=owner, title=title)


def make_revision(project, title="Дроби") -> Revision:
    document = {
        "format": "knowledge-tester/test",
        "version": 1,
        "test": {"title": title, "questions": []},
    }
    assessment = Assessment.objects.create(project=project, title=title, document=document)
    return Revision.objects.create(
        assessment=assessment, number=1, document=document, content_hash="h"
    )


def make_sitting(revision, owner, title="Контрольна", code=None) -> Sitting:
    return Sitting.objects.create(
        revision=revision,
        code=code or f"T{next(_codes):05d}",
        title=title,
        created_by=owner,
    )


def make_attempt(
    sitting,
    student=None,
    *,
    percent: str | None = "80.0",
    max_score: str = "10.00",
    status: str = Attempt.Status.SUBMITTED,
    pending: int = 0,
    days: int = 0,
    grade: str = "",
    name: str = "typed name",
    scored: bool = True,
) -> Attempt:
    """A finished attempt `days` after BASE_TIME with the given percent (score derived)."""
    attempt = Attempt.objects.create(
        sitting=sitting, student=student, taker={"name": name}, status=status
    )
    values: dict = {"pending_reviews": pending, "grade": grade}
    if status in (Attempt.Status.SUBMITTED, Attempt.Status.AUTO_SUBMITTED):
        values["submitted_at"] = BASE_TIME + timedelta(days=days)
    if scored and status != Attempt.Status.IN_PROGRESS:
        maximum = Decimal(max_score)
        values["max_score"] = maximum
        if percent is None:
            values["score"], values["percent"] = Decimal("0.00"), None
        else:
            values["percent"] = Decimal(percent)
            values["score"] = (maximum * Decimal(percent) / 100).quantize(Decimal("0.01"))
    Attempt.objects.filter(pk=attempt.pk).update(**values)
    attempt.refresh_from_db()
    return attempt
