"""Row factories for the gradebook tests (plain functions, no fixtures).

Not collected by pytest (the name does not start with `test_`). Rows are created directly
through the ORM: the gradebook only reads `Group`, `Student`, `Sitting` and `Attempt`.
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from apps.assessments.models import Assessment, Project, Revision
from apps.delivery.models import Attempt, Sitting
from apps.people.models import Group, Student

_codes = itertools.count(1)
BASE_TIME = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)


def make_project(owner, title="Maths"):
    return Project.objects.create(owner=owner, title=title)


def make_revision(owner, title="Fractions", project=None) -> Revision:
    project = project or make_project(owner)
    document = {
        "format": "knowledge-tester/test",
        "version": 1,
        "test": {"title": title, "questions": []},
    }
    assessment = Assessment.objects.create(project=project, title=title, document=document)
    return Revision.objects.create(
        assessment=assessment, number=1, document=document, content_hash="x", created_by=owner
    )


def make_group(owner, name="7-A") -> Group:
    return Group.objects.create(owner=owner, name=name)


def make_student(owner, group, name, *, active=True) -> Student:
    return Student.objects.create(owner=owner, group=group, full_name=name, is_active=active)


def make_sitting(
    owner,
    revision=None,
    *,
    group=None,
    title="",
    days=0,
    project=None,
    test_title="Fractions",
) -> Sitting:
    """A session `days` days after BASE_TIME (the creation time decides the column order)."""
    revision = revision or make_revision(owner, test_title, project)
    sitting = Sitting.objects.create(
        revision=revision,
        code=f"T{next(_codes):05d}",
        title=title,
        group=group,
        created_by=owner,
    )
    Sitting.objects.filter(pk=sitting.pk).update(created_at=BASE_TIME + timedelta(days=days))
    sitting.refresh_from_db()
    return sitting


def attempt_fields(
    sitting,
    student,
    percent,
    *,
    status=Attempt.Status.SUBMITTED,
    pending=0,
    grade="",
    score="auto",
) -> dict:
    percent = None if percent is None else Decimal(str(percent))
    if score == "auto":
        score = None if percent is None else percent / 10
    return {
        "sitting": sitting,
        "student": student,
        "taker": {"name": student.full_name if student else "Anon"},
        "status": status,
        "score": score,
        "max_score": Decimal(10),
        "percent": percent,
        "grade": grade,
        "pending_reviews": pending,
        "submitted_at": BASE_TIME if status != Attempt.Status.IN_PROGRESS else None,
    }


def make_attempt(sitting, student, percent, **kwargs) -> Attempt:
    return Attempt.objects.create(**attempt_fields(sitting, student, percent, **kwargs))
