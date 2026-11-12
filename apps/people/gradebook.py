"""Group gradebook (plan §14, KT-606): a matrix of the group's students by sessions.

Pure data preparation, no HTTP. The view and the CSV export both render a `Gradebook`.

Rules (people-contracts.md, "Gradebook"):

- Columns are the sessions bound to the group (`Sitting.group`) plus any session that has a
  non-voided attempt linked to a student of the group, oldest first.
- Rows are the group's students: active ones always, inactive ones only if they have a result.
- A cell is the percent of the student's BEST counted attempt in that session. Counted means
  submitted or auto-submitted, with a score, not voided. Ties go to the attempt that is not
  provisional, then to the later one.
- A cell is provisional when that attempt still has answers waiting for review.
- Averages are plain means of the shown cells (the best percents), rounded half up to 0.1.

The number of queries is constant: students, sessions, attempts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from apps.delivery.models import Attempt, Sitting

from .models import Group, Student
from .names import normalize_name

FINISHED = (Attempt.Status.SUBMITTED, Attempt.Status.AUTO_SUBMITTED)
ONE_DECIMAL = Decimal("0.1")

# Colour bands for a cell (always shown together with the number and a hidden word).
OK_FROM = Decimal(60)
WARN_FROM = Decimal(40)

# Ukrainian alphabet order (code-point order puts і, ї, є, ґ after я).
_UK_ALPHABET = "абвгґдеєжзиіїйклмнопрстуфхцчшщьюя"
_UK_ORDER = {ch: 0x400 + i for i, ch in enumerate(_UK_ALPHABET)}


def alpha_key(name: str) -> tuple[int, ...]:
    """Sort key that orders names the way a Ukrainian class list is ordered."""
    text = normalize_name(name)
    return tuple(_UK_ORDER.get(ch, ord(ch) if ord(ch) < 0x400 else 0x1000 + ord(ch)) for ch in text)


def band(percent: Decimal) -> str:
    """'ok' (>= 60), 'warn' (40 to 59.9) or 'bad' (< 40)."""
    if percent >= OK_FROM:
        return "ok"
    if percent >= WARN_FROM:
        return "warn"
    return "bad"


def mean(values: list[Decimal]) -> Decimal | None:
    """Average rounded half up to one decimal place, None for no values."""
    if not values:
        return None
    return (sum(values, Decimal(0)) / len(values)).quantize(ONE_DECIMAL, rounding=ROUND_HALF_UP)


@dataclass
class Cell:
    """The best counted attempt of one student in one session."""

    percent: Decimal
    grade: str
    attempt_id: int
    attempts: int  # counted attempts of this student in the session (1 = only one)
    provisional: bool

    @property
    def band(self) -> str:
        return band(self.percent)

    @property
    def show_grade(self) -> bool:
        """The plain percent scale writes '85.0 %' as the grade: no need to repeat it."""
        return bool(self.grade) and not self.grade.endswith("%")


@dataclass
class Column:
    """One session."""

    sitting_id: int
    title: str  # the session title, or the test title when the session has none
    test_title: str
    code: str
    date: date
    bound: bool  # bound to the group (False = only linked after the fact)
    average: Decimal | None = None
    provisional: bool = False  # some cell in the column is provisional
    takers: int = 0  # students with a cell

    @property
    def subtitle(self) -> str:
        """The test title, when it adds something to the session title."""
        return self.test_title if self.test_title != self.title else ""


@dataclass
class Row:
    student: Student
    cells: list[Cell | None]
    average: Decimal | None = None
    provisional: bool = False  # some cell in the row is provisional
    filled: int = 0


@dataclass
class Gradebook:
    group: Group
    columns: list[Column] = field(default_factory=list)
    rows: list[Row] = field(default_factory=list)
    overall_average: Decimal | None = None
    overall_provisional: bool = False
    has_multiple: bool = False  # some cell stands for more than one attempt
    has_grades: bool = False  # some cell shows a grade under the percent

    @property
    def is_empty(self) -> bool:
        return not self.rows or not self.columns

    @property
    def has_provisional(self) -> bool:
        return self.overall_provisional


def _start_of_day(value: date | datetime) -> datetime:
    if isinstance(value, datetime):
        return value if timezone.is_aware(value) else timezone.make_aware(value)
    return timezone.make_aware(datetime.combine(value, time.min))


def _sessions(group: Group, project, since, viewer) -> list[Sitting]:
    linked = Attempt.objects.filter(sitting=OuterRef("pk"), student__group=group).exclude(
        status=Attempt.Status.VOIDED
    )
    sittings = (
        Sitting.objects.filter(Q(group=group) | Exists(linked))
        .select_related("revision__assessment")
        .order_by("created_at", "pk")
    )
    if viewer is not None and not viewer.is_admin_role:
        # A teacher never sees a column (or its results) of somebody else's session.
        sittings = sittings.filter(created_by=viewer)
    if project is not None:
        sittings = sittings.filter(revision__assessment__project=project)
    if since is not None:
        sittings = sittings.filter(created_at__gte=_start_of_day(since))
    return list(sittings)


def _best(attempts: list[Attempt]) -> Attempt:
    return max(
        attempts,
        key=lambda a: (
            a.percent,
            a.pending_reviews == 0,
            a.submitted_at or a.started_at,
            a.pk,
        ),
    )


def build_gradebook(group: Group, *, project=None, since=None, viewer=None) -> Gradebook:
    """The gradebook of `group`.

    `project` limits the columns to the sessions of one project, `since` (a date or datetime)
    to the sessions opened on or after it. `viewer` (a user) hides sessions of other teachers
    unless the viewer is an admin; the view always passes it.
    """
    students = list(Student.objects.filter(group=group))
    sittings = _sessions(group, project, since, viewer)
    book = Gradebook(group=group)
    book.columns = [
        Column(
            sitting_id=s.pk,
            title=s.title or s.revision.test.get("title", "") or s.code,
            test_title=s.revision.test.get("title", "") or s.revision.assessment.title,
            code=s.code,
            date=timezone.localtime(s.created_at).date(),
            bound=s.group_id == group.pk,
        )
        for s in sittings
    ]
    index = {s.pk: i for i, s in enumerate(sittings)}

    counted = (
        Attempt.objects.filter(
            student__group=group,
            sitting_id__in=list(index),
            status__in=FINISHED,
            score__isnull=False,
            percent__isnull=False,
        )
        .only(
            "sitting_id",
            "student_id",
            "percent",
            "grade",
            "pending_reviews",
            "started_at",
            "submitted_at",
        )
        .order_by("pk")
    )
    grouped: dict[tuple[int, int], list[Attempt]] = {}
    for attempt in counted:
        grouped.setdefault((attempt.student_id, attempt.sitting_id), []).append(attempt)

    rows: list[Row] = []
    for student in students:
        cells: list[Cell | None] = [None] * len(sittings)
        for sitting in sittings:
            attempts = grouped.get((student.pk, sitting.pk))
            if attempts:
                best = _best(attempts)
                cells[index[sitting.pk]] = Cell(
                    percent=best.percent,
                    grade=best.grade,
                    attempt_id=best.pk,
                    attempts=len(attempts),
                    provisional=best.pending_reviews > 0,
                )
        filled = [c for c in cells if c is not None]
        if not student.is_active and not filled:
            continue
        rows.append(
            Row(
                student=student,
                cells=cells,
                average=mean([c.percent for c in filled]),
                provisional=any(c.provisional for c in filled),
                filled=len(filled),
            )
        )
    # Active students first, then the inactive ones that have results; each in class-list order.
    rows.sort(key=lambda r: (not r.student.is_active, alpha_key(r.student.full_name), r.student.pk))
    book.rows = rows

    everything: list[Cell] = []
    for i, column in enumerate(book.columns):
        cells = [row.cells[i] for row in rows if row.cells[i] is not None]
        column.takers = len(cells)
        column.average = mean([c.percent for c in cells])
        column.provisional = any(c.provisional for c in cells)
        everything.extend(cells)
    book.overall_average = mean([c.percent for c in everything])
    book.overall_provisional = any(c.provisional for c in everything)
    book.has_multiple = any(c.attempts > 1 for c in everything)
    book.has_grades = any(c.show_grade for c in everything)
    return book
