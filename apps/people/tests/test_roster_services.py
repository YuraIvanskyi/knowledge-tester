"""Roster services: sorting, groups, students, duplicates, PINs, import preview and apply."""

import pytest

from apps.assessments.models import Assessment, Project, Revision
from apps.delivery.models import Attempt, Sitting
from apps.people import services
from apps.people.importing import ParsedRow
from apps.people.models import Group, Student

pytestmark = pytest.mark.django_db


def row(name, group=""):
    return ParsedRow(name, group)


def make_students(owner, group, names):
    return [Student.objects.create(owner=owner, group=group, full_name=n) for n in names]


# ---- sorting ---------------------------------------------------------------------------------


def test_ukrainian_alphabet_order():
    names = ["Ярослав", "Іван", "Євген", "Ґанна", "Григорій", "Андрій", "Їжак", "Йосип", "Ніна"]
    assert sorted(names, key=services.uk_sort_key) == [
        "Андрій",
        "Григорій",
        "Ґанна",
        "Євген",
        "Іван",
        "Їжак",
        "Йосип",
        "Ніна",
        "Ярослав",
    ]
    assert services.uk_sort_key("АБВ") == services.uk_sort_key("абв")


def test_natural_group_order():
    names = ["10-А", "7-Б", "7-А", "9", "Фізика"]
    assert sorted(names, key=services.natural_group_key) == ["7-А", "7-Б", "9", "10-А", "Фізика"]


def test_sort_students(teacher):
    group = Group.objects.create(owner=teacher, name="g")
    students = make_students(teacher, group, ["Яременко Оксана", "Іваненко Петро", "Андрієнко Ада"])
    assert [s.full_name for s in services.sort_students(students)] == [
        "Андрієнко Ада",
        "Іваненко Петро",
        "Яременко Оксана",
    ]


# ---- groups ----------------------------------------------------------------------------------


def test_group_names_are_unique_per_owner_and_friendly(teacher, other_teacher):
    group = services.create_group(teacher, name=" 7-А ", note="  first  ")
    assert (group.name, group.note) == ("7-А", "first")
    with pytest.raises(services.GroupNameTaken):
        services.create_group(teacher, name="7-а")
    with pytest.raises(services.GroupNameTaken):
        services.create_group(teacher, name="7-А")
    services.create_group(other_teacher, name="7-А")  # another owner may reuse it

    other = services.create_group(teacher, name="7-Б")
    with pytest.raises(services.GroupNameTaken):
        services.update_group(other, name="7-а", note="", is_archived=False)
    updated = services.update_group(other, name="7-Б", note="n", is_archived=True)
    assert updated.is_archived and updated.note == "n"


def test_student_and_group_must_share_an_owner(teacher, other_teacher):
    foreign = Group.objects.create(owner=other_teacher, name="x")
    with pytest.raises(ValueError, match="same owner"):
        services.create_student(teacher, full_name="Іван Петренко", group=foreign)
    student = services.create_student(teacher, full_name="Іван Петренко")
    with pytest.raises(ValueError, match="same owner"):
        services.update_student(
            student, full_name="Іван Петренко", group=foreign, pin="", notes="", is_active=True
        )


def test_update_student_refreshes_the_name_key(teacher):
    student = services.create_student(teacher, full_name="Іван  Петренко", notes=" a ")
    assert (student.full_name, student.name_key, student.notes) == (
        "Іван Петренко",
        "іван петренко",
        "a",
    )
    services.update_student(
        student, full_name="Олена Коваль", group=None, pin="1357", notes="", is_active=False
    )
    student.refresh_from_db()
    assert (student.name_key, student.pin, student.is_active) == ("олена коваль", "1357", False)


def make_attempts(owner, group, student):
    project = Project.objects.create(owner=owner, title="P")
    assessment = Assessment.objects.create(project=project, title="T", document={"test": {}})
    revision = Revision.objects.create(
        assessment=assessment, number=1, document={"test": {}}, content_hash="x"
    )
    sitting = Sitting.objects.create(
        revision=revision, code="ABC234", group=group, created_by=owner
    )
    return sitting, Attempt.objects.create(sitting=sitting, student=student, taker={"name": "x"})


def test_group_impact_counts(teacher):
    group = Group.objects.create(owner=teacher, name="7-А")
    one, two = make_students(teacher, group, ["Іван Петренко", "Олена Коваль"])
    two.is_active = False
    two.save()
    make_attempts(teacher, group, one)
    impact = services.group_impact(group)
    assert (impact.students, impact.active_students, impact.sessions, impact.attempts) == (
        2,
        1,
        1,
        1,
    )


def test_delete_group_keeping_students(teacher):
    group = Group.objects.create(owner=teacher, name="7-А")
    one, _two = make_students(teacher, group, ["Іван Петренко", "Олена Коваль"])
    sitting, attempt = make_attempts(teacher, group, one)

    assert services.delete_group(group, delete_students=False) == 0

    assert not Group.objects.filter(pk=group.pk).exists()
    one.refresh_from_db()
    assert one.group is None
    attempt.refresh_from_db()
    assert attempt.student_id == one.pk  # still linked
    sitting.refresh_from_db()
    assert sitting.group is None  # the session itself stays


def test_delete_group_with_students_only_unlinks_attempts(teacher):
    group = Group.objects.create(owner=teacher, name="7-А")
    other_group = Group.objects.create(owner=teacher, name="7-Б")
    one, _two = make_students(teacher, group, ["Іван Петренко", "Олена Коваль"])
    keep = make_students(teacher, other_group, ["Інша Дитина"])[0]
    _sitting, attempt = make_attempts(teacher, group, one)

    group_pk = group.pk
    assert services.delete_group(group, delete_students=True) == 2

    assert Student.objects.filter(group_id=group_pk).count() == 0
    assert Student.objects.filter(owner=teacher).count() == 1
    assert Student.objects.filter(pk=keep.pk).exists()
    assert Attempt.objects.filter(pk=attempt.pk).exists()  # never deleted
    attempt.refresh_from_db()
    assert attempt.student_id is None
    assert attempt.taker == {"name": "x"}


# ---- duplicates ------------------------------------------------------------------------------


def test_find_duplicates_same_reordered_and_foreign(teacher, other_teacher):
    group = Group.objects.create(owner=teacher, name="7-А")
    ivan = Student.objects.create(owner=teacher, group=group, full_name="Іваненко Дем’ян")
    Student.objects.create(owner=teacher, full_name="Коваль Олена")
    Student.objects.create(owner=other_teacher, full_name="Іваненко Дем'ян")

    same = services.find_duplicates(teacher, "  ІВАНЕНКО   дем'ян ")
    assert [(d.student.pk, d.kind) for d in same] == [(ivan.pk, "same")]
    swapped = services.find_duplicates(teacher, "Дем'ян Іваненко")
    assert [(d.student.pk, d.kind) for d in swapped] == [(ivan.pk, "reordered")]
    assert services.find_duplicates(teacher, "Іваненко Дем'ян", exclude_pk=ivan.pk) == []
    assert services.find_duplicates(teacher, "Іваненко Петро") == []
    assert services.find_duplicates(teacher, "") == []
    assert services.find_duplicates(teacher, "***") == []
    # only whole words match: "Олен" is not "Олена"
    assert services.find_duplicates(teacher, "Коваль Олен") == []


# ---- PINs ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pin", "weak"),
    [
        ("0000", True),
        ("7777", True),
        ("1234", True),
        ("4321", True),
        ("2345", True),
        ("1212", True),
        ("1357", False),
        ("2580", False),
        ("0473", False),
        ("1233", False),
    ],
)
def test_weak_pins(pin, weak):
    assert services._weak_pin(pin) is weak


def test_new_pin_is_four_digits_strong_and_avoids_taken():
    for _ in range(200):
        pin = services.new_pin({"1357"})
        assert len(pin) == 4 and pin.isdigit() and pin != "1357"
        assert not services._weak_pin(pin)


def test_new_pin_when_almost_every_pin_is_taken():
    free = "1357"
    taken = {f"{n:04d}" for n in range(10_000)} - {free}
    assert services.new_pin(taken) == free
    with pytest.raises(ValueError, match="No free PIN"):
        services.new_pin(taken | {free})


def test_generate_pins_only_for_students_without_one(teacher):
    group = Group.objects.create(owner=teacher, name="7-А")
    has, lacks, gone = make_students(teacher, group, ["А Один", "Б Два", "В Три"])
    has.pin = "4821"
    has.save()
    gone.is_active = False
    gone.save()

    assert services.generate_pins(group) == 1
    for student in (has, lacks, gone):
        student.refresh_from_db()
    assert has.pin == "4821"  # untouched
    assert len(lacks.pin) == 4 and lacks.pin != "4821"
    assert gone.pin == ""  # inactive students are skipped
    assert services.generate_pins(group) == 0  # nothing left to do


def test_generate_pins_unique_inside_the_group(teacher):
    group = Group.objects.create(owner=teacher, name="big")
    other = Group.objects.create(owner=teacher, name="small")
    Student.objects.bulk_create(
        [
            Student(owner=teacher, group=group, full_name=f"Учень {i}", name_key=f"учень {i}")
            for i in range(300)
        ]
    )
    foreign_pin = Student.objects.create(owner=teacher, group=other, full_name="Інший", pin="9246")
    assert services.generate_pins(group) == 300
    pins = list(Student.objects.filter(group=group).values_list("pin", flat=True))
    assert len(set(pins)) == 300
    assert all(len(p) == 4 and not services._weak_pin(p) for p in pins)
    foreign_pin.refresh_from_db()
    assert foreign_pin.pin == "9246"


def test_regenerate_changes_every_active_pin(teacher):
    group = Group.objects.create(owner=teacher, name="7-А")
    students = make_students(teacher, group, [f"Учень {i}" for i in range(20)])
    services.generate_pins(group)
    before = {s.pk: s.pin for s in Student.objects.filter(group=group)}
    assert services.generate_pins(group, regenerate=True) == 20
    after = {s.pk: s.pin for s in Student.objects.filter(group=group)}
    assert all(before[pk] != after[pk] for pk in before)
    assert len(set(after.values())) == len(students)


# ---- import preview --------------------------------------------------------------------------


def test_preview_classifies_new_duplicate_and_invalid(teacher):
    group = Group.objects.create(owner=teacher, name="7-А")
    Student.objects.create(owner=teacher, group=group, full_name="Іваненко Дем’ян")
    rows = [
        row("Нова Людина", "7-А"),
        row("ІВАНЕНКО  дем'ян", "7-А"),  # same name as an existing student
        row("Дем'ян Іваненко", "7-А"),
        row("Мельник Олена", "8-Б"),
        row("Олена Мельник"),  # reordered duplicate of the earlier row
        row("Мельник Олена"),  # same as the earlier row
        row("12345"),
        ParsedRow("Хтось", "", ["too_long"]),  # issues from the parser are kept
    ]
    preview = services.build_preview(teacher, rows)
    statuses = [r.status for r in preview.rows]
    assert statuses == [
        "new",
        "duplicate",
        "duplicate",
        "new",
        "duplicate",
        "duplicate",
        "invalid",
        "invalid",
    ]
    assert preview.rows[1].duplicate_of == "Іваненко Дем’ян (7-А)"
    assert preview.rows[1].duplicate_kind == "same"
    assert preview.rows[2].duplicate_kind == "reordered"
    assert "row 4" in preview.rows[4].duplicate_of and preview.rows[4].duplicate_kind == "reordered"
    assert preview.rows[5].duplicate_kind == "same"
    assert preview.rows[6].problems and preview.rows[7].problems
    assert (preview.n_new, preview.n_duplicate, preview.n_invalid) == (2, 4, 2)
    # existing group is matched ignoring case; an unknown one is announced as new, once
    assert (preview.rows[0].group_name, preview.rows[0].group_is_new) == ("7-А", False)
    assert preview.rows[3].group_is_new and preview.new_groups == ["8-Б"]


def test_preview_group_resolution_and_default(teacher, other_teacher):
    mine = Group.objects.create(owner=teacher, name="7-А")
    Group.objects.create(owner=other_teacher, name="9-В")
    rows = [row("А Один", "7-а"), row("Б Два", "9-В"), row("В Три", "9-в"), row("Г Чотири")]
    preview = services.build_preview(teacher, rows)
    assert [(r.group_name, r.group_is_new) for r in preview.rows] == [
        ("7-А", False),
        ("9-В", True),  # the other teacher's group is invisible: this would be a new one
        ("9-В", True),
        ("", False),
    ]
    assert preview.new_groups == ["9-В"]

    with_default = services.build_preview(teacher, rows, default_group=mine)
    assert with_default.rows[3].group_name == "7-А" and not with_default.rows[3].group_is_new
    with_new = services.build_preview(teacher, rows, new_group_name=" Гурток ")
    assert (with_new.rows[3].group_name, with_new.rows[3].group_is_new) == ("Гурток", True)
    assert with_new.new_groups == ["9-В", "Гурток"]


def test_preview_does_not_write(teacher):
    services.build_preview(teacher, [row("А Один", "Нова")])
    assert Group.objects.count() == 0 and Student.objects.count() == 0


# ---- import apply ----------------------------------------------------------------------------


def test_apply_import_creates_groups_and_students_once(teacher):
    rows = [
        row("Іваненко Петро", "7-А"),
        row("Коваль Олена", "7-а"),
        row("Мельник Іра", "7-Б"),
        row("Без Групи"),
        row("12345"),
    ]
    result = services.apply_import(teacher, rows)
    assert (result.created, result.groups_created, result.skipped_invalid) == (4, 2, 1)
    assert result.groups_used == 2 and result.group is None
    assert sorted(Group.objects.values_list("name", flat=True)) == ["7-А", "7-Б"]
    petro = Student.objects.get(full_name="Іваненко Петро")
    assert petro.name_key == "іваненко петро" and petro.group.name == "7-А"
    assert petro.owner == teacher and petro.is_active and petro.pin == ""
    assert Student.objects.get(full_name="Коваль Олена").group_id == petro.group_id
    assert Student.objects.get(full_name="Без Групи").group is None


def test_apply_import_into_an_existing_group_reports_the_single_group(teacher):
    group = Group.objects.create(owner=teacher, name="7-А")
    result = services.apply_import(teacher, [row("А Один"), row("Б Два")], default_group=group)
    assert result.created == 2 and result.groups_created == 0 and result.group == group
    assert group.students.count() == 2


def test_apply_import_skips_duplicates_by_default_and_can_include_them(teacher):
    Student.objects.create(owner=teacher, full_name="Іваненко Петро")
    rows = [row("Петро Іваненко"), row("Коваль Олена"), row("Коваль Олена")]
    result = services.apply_import(teacher, rows)
    assert (result.created, result.skipped_duplicates) == (1, 2)
    assert Student.objects.count() == 2

    result = services.apply_import(teacher, rows, skip_duplicates=False)
    assert (result.created, result.skipped_duplicates) == (3, 0)
    assert Student.objects.count() == 5


def test_apply_import_respects_selection_and_makes_no_group_for_unticked_rows(teacher):
    rows = [row("А Один", "Нова"), row("Б Два", "Друга"), row("В Три", "Друга")]
    result = services.apply_import(teacher, rows, selected=[0, 2])
    assert (result.created, result.skipped_unticked, result.groups_created) == (2, 1, 2)
    assert sorted(Group.objects.values_list("name", flat=True)) == ["Друга", "Нова"]

    Group.objects.all().delete()
    result = services.apply_import(teacher, rows, selected=[])
    assert result.created == 0 and result.skipped_unticked == 3
    assert Group.objects.count() == 0


def test_apply_import_is_atomic(teacher, monkeypatch):
    def boom(objs, *args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(Student.objects, "bulk_create", boom)
    with pytest.raises(RuntimeError):
        services.apply_import(teacher, [row("А Один", "Нова")])
    assert Group.objects.count() == 0 and Student.objects.count() == 0


def test_apply_import_does_not_trust_stale_issue_lists(teacher):
    # A row whose stored issue list was emptied is checked again from its content.
    result = services.apply_import(teacher, [ParsedRow("12345", "", [])])
    assert result.created == 0 and result.skipped_invalid == 1


def test_admin_import_into_a_teachers_group_stays_in_that_roster(teacher, admin_user):
    group = Group.objects.create(owner=teacher, name="7-А")
    result = services.apply_import(admin_user, [row("А Один", "Нова")], default_group=group)
    assert result.created == 1
    student = Student.objects.get()
    assert student.owner == teacher and student.group.owner == teacher


def test_preview_and_apply_use_a_fixed_number_of_queries(teacher, django_assert_max_num_queries):
    Student.objects.bulk_create(
        [
            Student(owner=teacher, full_name=f"Існуючий {i}", name_key=f"існуючий {i}")
            for i in range(300)
        ]
    )
    rows = [row(f"Учень {i}", f"Група {i % 5}") for i in range(600)]
    with django_assert_max_num_queries(4):
        preview = services.build_preview(teacher, rows)
    assert preview.n_new == 600 and len(preview.new_groups) == 5
    # savepoint + preview reads + groups + one insert per new group + one bulk insert
    with django_assert_max_num_queries(16):
        result = services.apply_import(teacher, rows)
    assert result.created == 600 and result.groups_created == 5
