"""Group-bound sessions (plan §14, KT-603): the "pick your name" list, the optional PIN and
the per-student attempt limit.

PRIVACY NOTE: the class list is visible to anyone who has the session link (that is the point:
no login). So the taker pages get names only: never PINs, notes, or anything beyond the id the
form posts back. The list is never rendered for a closed session. A posted student id is always
re-checked against the session's own group; it is never trusted.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass

from django.core.cache import cache
from django.utils.translation import gettext as _

from apps.core.text import uk_sort_key
from apps.people.models import Student
from apps.people.names import normalize_name

from .models import Attempt, Sitting

# Wrong PINs allowed per student inside one window, then "try again later". Per student, not
# per session, so the same PIN cannot be guessed through a second session. Anyone with the link
# can lock a classmate out for a few minutes this way; that is accepted for a classroom tool.
PIN_MAX_FAILURES = 5
PIN_WINDOW_SECONDS = 5 * 60


def name_sort_key(name: str) -> tuple:
    """Case-insensitive sort key that orders Ukrainian names alphabetically."""
    return uk_sort_key(" ".join((name or "").split()))


def is_group_bound(sitting: Sitting | None) -> bool:
    return bool(sitting is not None and sitting.group_id)


def active_students(sitting: Sitting) -> list[Student]:
    """The group's active students, sorted by name (one query)."""
    if not is_group_bound(sitting):
        return []
    students = sitting.group.students.filter(is_active=True)
    return sorted(students, key=lambda s: name_sort_key(s.full_name))


def picker_options(sitting: Sitting) -> list[dict]:
    """What the taker page may see of the class: id, name, and whether the name can be picked.
    In a PIN session a student without a PIN cannot be picked (nobody could enter it)."""
    options = []
    for student in active_students(sitting):
        options.append(
            {
                "id": student.pk,
                "name": student.full_name,
                "selectable": bool(student.pin.strip()) or not sitting.use_pin,
            }
        )
    return options


def parse_student_id(raw) -> int | None:
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def find_student(sitting: Sitting, raw_id) -> Student | None:
    """The posted student, only if active and in THIS session's group; else None."""
    student_id = parse_student_id(raw_id)
    if student_id is None or not is_group_bound(sitting):
        return None
    return sitting.group.students.filter(pk=student_id, is_active=True).first()


# --- PIN ---------------------------------------------------------------------------------------


def _fail_key(student: Student) -> str:
    return f"kt:pin-fail:{student.pk}"


def pin_is_throttled(student: Student) -> bool:
    return cache.get(_fail_key(student), 0) >= PIN_MAX_FAILURES


def _record_failure(student: Student) -> None:
    key = _fail_key(student)
    # `add` starts the window at the first failure; `incr` keeps its expiry.
    if not cache.add(key, 1, PIN_WINDOW_SECONDS):
        try:
            cache.incr(key)
        except ValueError:  # expired between the two calls
            cache.add(key, 1, PIN_WINDOW_SECONDS)


def _clean_pin(value) -> str:
    return "".join(str(value or "").split()).casefold()


def pin_errors(student: Student, entered) -> list[str]:
    """Check a typed PIN. Empty list = accepted (and the failure counter is reset)."""
    if not student.pin.strip():
        return [_("This name has no PIN yet. Ask your teacher.")]
    if pin_is_throttled(student):
        # Refuse without comparing: a right guess must not be confirmed while locked.
        return [_("Too many wrong PINs for this name. Please try again in a few minutes.")]
    typed = _clean_pin(entered)
    if not typed:
        return [_("Please type your PIN.")]
    if not hmac.compare_digest(typed.encode(), _clean_pin(student.pin).encode()):
        _record_failure(student)
        return [_("The PIN is not correct.")]
    cache.delete(_fail_key(student))
    return []


# --- attempt limit -----------------------------------------------------------------------------


def attempts_used_by_student(sitting: Sitting, student: Student) -> int:
    """Attempts already made by this student (voided ones do not count).

    Counts attempts linked to the student, plus unlinked attempts typed with the same name
    (for example from before a teacher linked things by hand). An attempt the teacher linked
    to somebody else is not counted for this name."""
    key = normalize_name(student.full_name)
    rows = sitting.attempts.exclude(status=Attempt.Status.VOIDED).values_list("student_id", "taker")
    used = 0
    for student_id, taker in rows:
        if student_id == student.pk or (
            student_id is None and normalize_name((taker or {}).get("name", "")) == key
        ):
            used += 1
    return used


# --- one call for the three places that start an attempt ---------------------------------------


@dataclass
class Entry:
    student: Student | None
    errors: list[str]


def check_entry(sitting: Sitting, data, *, max_attempts: int) -> Entry:
    """Validate the picked student (+ PIN) from posted data (QueryDict or JSON dict).

    Order matters: the student is validated first, the PIN is only compared (and counted
    against the throttle) when it is a real class member, and the attempt limit is only reported
    after the PIN was right, so a stranger learns nothing about who already took the test."""
    student = find_student(sitting, data.get("student"))
    if student is None:
        return Entry(None, [_("Please choose your name from the list.")])
    if sitting.use_pin:
        errors = pin_errors(student, data.get("pin"))
        if errors:
            return Entry(student, errors)
    if attempts_used_by_student(sitting, student) >= max_attempts:
        return Entry(student, [_("You have already taken this test.")])
    return Entry(student, [])


def group_summary(sitting: Sitting) -> dict:
    """Counts for the teacher: active students, and how many of them have no PIN."""
    students = sitting.group.students.filter(is_active=True) if sitting.group_id else []
    total = len(students)
    return {
        "students": total,
        "no_pin": sum(1 for s in students if not s.pin.strip()),
    }
