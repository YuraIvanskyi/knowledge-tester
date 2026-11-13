"""Roster operations: every database write for groups, students, PINs and imports (KT-602).

Views never write rows themselves. Ownership rule enforced here as well as in the views:
`student.owner == group.owner`, and a foreign group is never accepted.

Phase 7 (LLM import) reuses `build_preview` / `apply_import` with rows it produced itself.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Iterable
from dataclasses import dataclass, field

from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _

from apps.core.text import uk_sort_key

from . import importing
from .importing import ParsedRow
from .models import Group, Student
from .names import normalize_name, same_person_key

# ---- sorting (SQLite orders by code point, which puts Ukrainian "І" after "Я") -------------


def natural_group_key(name: str) -> list:
    """'7-А' before '10-А': digits compare as numbers, the rest in alphabet order."""
    return [
        (0, int(part)) if part.isdigit() else (1, uk_sort_key(part))
        for part in re.split(r"(\d+)", name)
        if part
    ]


def sort_students(students: Iterable[Student]) -> list[Student]:
    return sorted(students, key=lambda s: uk_sort_key(s.name_key or normalize_name(s.full_name)))


# ---- ownership invariants ------------------------------------------------------------------


def _check_group_owner(owner_id: int, group: Group | None) -> None:
    if group is not None and group.owner_id != owner_id:
        raise ValueError("A student can only be placed in a group of the same owner.")


# ---- groups --------------------------------------------------------------------------------


class GroupNameTaken(ValueError):
    """The owner already has a group with this name."""


def group_name_taken(owner_id: int, name: str, *, exclude_pk: int | None = None) -> bool:
    """Case-, space- and apostrophe-insensitive: '7-А' and '7-а ' are the same group."""
    key = normalize_name(name)
    return any(
        normalize_name(existing.name) == key
        for existing in Group.objects.filter(owner_id=owner_id).exclude(pk=exclude_pk)
    )


def create_group(owner, *, name: str, note: str = "") -> Group:
    name = importing.clean(name)
    if group_name_taken(owner.pk, name):
        raise GroupNameTaken(name)
    try:
        with transaction.atomic():
            return Group.objects.create(owner=owner, name=name, note=note.strip())
    except IntegrityError:
        raise GroupNameTaken(name) from None


def update_group(group: Group, *, name: str, note: str, is_archived: bool) -> Group:
    name = importing.clean(name)
    if group_name_taken(group.owner_id, name, exclude_pk=group.pk):
        raise GroupNameTaken(name)
    group.name, group.note, group.is_archived = name, note.strip(), is_archived
    try:
        with transaction.atomic():
            group.save()
    except IntegrityError:
        raise GroupNameTaken(name) from None
    return group


@dataclass(frozen=True)
class GroupImpact:
    students: int
    active_students: int
    sessions: int  # sessions bound to the group
    attempts: int  # attempts linked to the group's students


def group_impact(group: Group) -> GroupImpact:
    from apps.delivery.models import Attempt  # delivery depends on people, not the reverse

    students = Student.objects.filter(group=group)
    return GroupImpact(
        students=students.count(),
        active_students=students.filter(is_active=True).count(),
        sessions=group.sittings.count(),
        attempts=Attempt.objects.filter(student__group=group).count(),
    )


def delete_group(group: Group, *, delete_students: bool) -> int:
    """Delete a group. Returns how many students were deleted along with it.

    Either way no attempt is deleted: the attempts of a deleted student are only unlinked
    (`Attempt.student` is SET_NULL) and sessions bound to the group lose their group.
    """
    with transaction.atomic():
        deleted = 0
        if delete_students:
            deleted = Student.objects.filter(group=group).count()
            Student.objects.filter(group=group).delete()
        group.delete()  # remaining students are kept, ungrouped (SET_NULL)
    return deleted


# ---- students ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Duplicate:
    student: Student
    kind: str  # "same" (same normalised name) or "reordered" (same words, other order)


def find_duplicates(owner, full_name: str, *, exclude_pk: int | None = None) -> list[Duplicate]:
    """The owner's students that are the same person by name (see apps.people.names)."""
    key = normalize_name(full_name)
    person = same_person_key(full_name)
    tokens = set(person.split())
    if not tokens:
        return []
    candidates = Student.objects.filter(owner=owner).select_related("group")
    for token in tokens:  # narrow in SQL (name_key is already case-folded), compare in Python
        candidates = candidates.filter(name_key__contains=token)
    if exclude_pk is not None:
        candidates = candidates.exclude(pk=exclude_pk)
    found = []
    for student in candidates:
        if student.name_key == key:
            found.append(Duplicate(student, "same"))
        elif same_person_key(student.full_name) == person:
            found.append(Duplicate(student, "reordered"))
    return sorted(found, key=lambda d: (d.kind != "same", uk_sort_key(d.student.full_name)))


def create_student(
    owner,
    *,
    full_name: str,
    group: Group | None = None,
    pin: str = "",
    notes: str = "",
    is_active: bool = True,
) -> Student:
    _check_group_owner(owner.pk, group)
    return Student.objects.create(
        owner=owner,
        group=group,
        full_name=importing.clean(full_name),
        pin=pin,
        notes=notes.strip(),
        is_active=is_active,
    )


def update_student(
    student: Student,
    *,
    full_name: str,
    group: Group | None,
    pin: str,
    notes: str,
    is_active: bool,
) -> Student:
    _check_group_owner(student.owner_id, group)
    student.full_name = importing.clean(full_name)
    student.group = group
    student.pin = pin
    student.notes = notes.strip()
    student.is_active = is_active
    student.save()
    return student


# ---- PINs ----------------------------------------------------------------------------------

PIN_DIGITS = 4


def _weak_pin(pin: str) -> bool:
    """Easy to guess: 0000, 1111, 1234, 4321, 1212."""
    digits = [int(ch) for ch in pin]
    steps = {b - a for a, b in zip(digits, digits[1:], strict=False)}
    return (
        len(set(pin)) == 1 or steps in ({1}, {-1}) or pin[: len(pin) // 2] == pin[len(pin) // 2 :]
    )


def new_pin(taken: set[str]) -> str:
    """A random 4-digit PIN that is not weak and not in `taken`."""
    space = 10**PIN_DIGITS
    for _attempt in range(2000):
        pin = f"{secrets.randbelow(space):0{PIN_DIGITS}d}"
        if pin not in taken and not _weak_pin(pin):
            return pin
    for number in range(space):  # nearly full group: take whatever is left
        pin = f"{number:0{PIN_DIGITS}d}"
        if pin not in taken and not _weak_pin(pin):
            return pin
    raise ValueError("No free PIN left in this group.")


def generate_pins(group: Group, *, regenerate: bool = False) -> int:
    """Give every active student of the group a PIN that is unique inside the group.

    By default only students without a PIN are touched; `regenerate=True` replaces all PINs of
    active students. Inactive students keep what they have. Returns how many were set.
    """
    with transaction.atomic():
        students = list(Student.objects.filter(group=group).order_by("pk"))
        targets = [s for s in students if s.is_active and (regenerate or not s.pin)]
        target_pks = {s.pk for s in targets}
        taken = {s.pin for s in students if s.pin and s.pk not in target_pks}
        for student in targets:
            student.pin = new_pin(taken | {student.pin})  # a regenerated PIN really changes
            taken.add(student.pin)
        Student.objects.bulk_update(targets, ["pin"])
    return len(targets)


# ---- import: preview and apply -------------------------------------------------------------

STATUS_NEW = "new"
STATUS_DUPLICATE = "duplicate"
STATUS_INVALID = "invalid"


@dataclass
class PreviewRow:
    index: int  # position in the parsed list: what the confirm form posts back
    full_name: str
    group_name: str  # the target group's name, "" = no group
    group_key: str
    group_is_new: bool
    status: str
    problems: list[str] = field(default_factory=list)  # readable reasons when invalid
    duplicate_of: str = ""
    duplicate_kind: str = ""  # "same" | "reordered"

    @property
    def is_invalid(self) -> bool:
        return self.status == STATUS_INVALID

    @property
    def is_duplicate(self) -> bool:
        return self.status == STATUS_DUPLICATE


@dataclass
class Preview:
    rows: list[PreviewRow]
    new_groups: list[str]

    @property
    def n_new(self) -> int:
        return sum(1 for r in self.rows if r.status == STATUS_NEW)

    @property
    def n_duplicate(self) -> int:
        return sum(1 for r in self.rows if r.status == STATUS_DUPLICATE)

    @property
    def n_invalid(self) -> int:
        return sum(1 for r in self.rows if r.status == STATUS_INVALID)


def import_owner(user, default_group: Group | None):
    """Whose roster an import goes into: the default group's owner, otherwise the user."""
    return default_group.owner if default_group is not None else user


def _student_label(student: Student) -> str:
    return f"{student.full_name} ({student.group.name})" if student.group else student.full_name


def build_preview(
    user, rows: Iterable[ParsedRow], default_group: Group | None = None, new_group_name: str = ""
) -> Preview:
    """Classify parsed rows against the owner's roster and against each other.

    `default_group` (a group the caller already checked the user may manage) or
    `new_group_name` applies to rows that have no group of their own. Nothing is written.
    """
    owner = import_owner(user, default_group)
    default_name = default_group.name if default_group else importing.clean(new_group_name)

    groups: dict[str, Group] = {}
    for group in Group.objects.filter(owner=owner).order_by("pk"):
        groups.setdefault(normalize_name(group.name), group)

    seen_name: dict[str, str] = {}
    seen_person: dict[str, str] = {}
    for student in Student.objects.filter(owner=owner).select_related("group").order_by("pk"):
        label = _student_label(student)
        seen_name.setdefault(student.name_key, label)
        seen_person.setdefault(same_person_key(student.full_name), label)

    new_group_names: dict[str, str] = {}
    result: list[PreviewRow] = []
    for index, row in enumerate(rows):
        name = importing.clean(row.full_name)
        group_name = importing.clean(row.group_name) or default_name
        codes = list(dict.fromkeys([*row.issues, *importing.issues_for(name, group_name)]))
        key = normalize_name(group_name)
        if codes:
            result.append(
                PreviewRow(
                    index,
                    name,
                    group_name,
                    "",
                    False,
                    STATUS_INVALID,
                    problems=[str(importing.ISSUE_LABELS.get(code, code)) for code in codes],
                )
            )
            continue

        existing = groups.get(key) if key else None
        if key and existing is None:
            group_name = new_group_names.setdefault(key, group_name)
        elif existing is not None:
            group_name = existing.name
        preview_row = PreviewRow(
            index, name, group_name, key, key != "" and existing is None, STATUS_NEW
        )

        name_key, person_key = normalize_name(name), same_person_key(name)
        if name_key in seen_name:
            preview_row.status, preview_row.duplicate_kind = STATUS_DUPLICATE, "same"
            preview_row.duplicate_of = seen_name[name_key]
        elif person_key in seen_person:
            preview_row.status, preview_row.duplicate_kind = STATUS_DUPLICATE, "reordered"
            preview_row.duplicate_of = seen_person[person_key]
        else:
            label = _("%(name)s (row %(n)s of this list)") % {"name": name, "n": index + 1}
            seen_name[name_key] = seen_person[person_key] = label
        result.append(preview_row)

    return Preview(rows=result, new_groups=list(new_group_names.values()))


@dataclass
class ImportResult:
    created: int = 0
    groups_created: int = 0
    skipped_duplicates: int = 0
    skipped_invalid: int = 0
    skipped_unticked: int = 0
    groups_used: int = 0
    group: Group | None = None  # set when every new student went into the same group


def apply_import(
    user,
    rows: Iterable[ParsedRow],
    default_group: Group | None = None,
    new_group_name: str = "",
    *,
    selected: Iterable[int] | None = None,
    skip_duplicates: bool = True,
) -> ImportResult:
    """Create the groups and students in one transaction.

    The rows are classified again here, so the database state at confirm time decides, not the
    preview the teacher looked at. `selected` = indexes of the rows to add (None = all).
    """
    owner = import_owner(user, default_group)
    chosen_indexes = None if selected is None else set(selected)
    result = ImportResult()
    with transaction.atomic():
        preview = build_preview(user, rows, default_group, new_group_name)
        chosen: list[PreviewRow] = []
        for row in preview.rows:
            if row.is_invalid:
                result.skipped_invalid += 1
            elif chosen_indexes is not None and row.index not in chosen_indexes:
                result.skipped_unticked += 1
            elif row.is_duplicate and skip_duplicates:
                result.skipped_duplicates += 1
            else:
                chosen.append(row)

        groups: dict[str, Group] = {}
        for group in Group.objects.filter(owner=owner).order_by("pk"):
            groups.setdefault(normalize_name(group.name), group)
        for row in chosen:
            if row.group_key and row.group_key not in groups:
                groups[row.group_key] = Group.objects.create(owner=owner, name=row.group_name)
                result.groups_created += 1

        students = [
            Student(
                owner=owner,
                group=groups.get(row.group_key) if row.group_key else None,
                full_name=row.full_name,
                name_key=normalize_name(row.full_name),
            )
            for row in chosen
        ]
        Student.objects.bulk_create(students)

    result.created = len(students)
    used = {s.group_id for s in students}
    result.groups_used = len({pk for pk in used if pk is not None})
    if len(used) == 1 and None not in used:
        result.group = next(g for g in groups.values() if g.pk in used)
    return result
