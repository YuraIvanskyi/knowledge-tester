"""Roster pages: groups, students, PINs. Ownership, POST-only changes, CSRF, duplicate flow."""

import pytest
from django.test import Client
from django.urls import reverse

from apps.people.models import Group, Student

pytestmark = pytest.mark.django_db


def messages_of(response):
    return [str(m) for m in response.context["messages"]]


@pytest.fixture
def mine(teacher):
    return Group.objects.create(owner=teacher, name="7-А")


@pytest.fixture
def theirs(other_teacher):
    return Group.objects.create(owner=other_teacher, name="8-Б")


@pytest.fixture
def my_student(teacher, mine):
    return Student.objects.create(owner=teacher, group=mine, full_name="Іваненко Петро")


@pytest.fixture
def their_student(other_teacher, theirs):
    return Student.objects.create(owner=other_teacher, group=theirs, full_name="Секретний Учень")


# ---- access ----------------------------------------------------------------------------------

PAGES = [
    ("people:groups", False),
    ("people:group_create", False),
    ("people:group", True),
    ("people:group_edit", True),
    ("people:group_delete", True),
    ("people:group_pins", True),
    ("people:students", False),
    ("people:student_create", False),
    ("people:student_edit", "student"),
    ("people:import", False),
]


def page_url(name, kind, mine, my_student):
    if kind == "student":
        return reverse(name, args=[my_student.pk])
    return reverse(name, args=[mine.pk]) if kind else reverse(name)


@pytest.mark.parametrize(("name", "kind"), PAGES)
def test_every_page_needs_a_login(client, mine, my_student, name, kind):
    response = client.get(page_url(name, kind, mine, my_student))
    assert response.status_code == 302
    assert response["Location"].startswith(reverse("accounts:login"))


def test_import_confirm_needs_a_login(client):
    response = client.post(reverse("people:import_confirm"))
    assert response.status_code == 302 and "login" in response["Location"]


@pytest.mark.parametrize(
    "name", ["people:group", "people:group_edit", "people:group_delete", "people:group_pins"]
)
def test_foreign_group_is_404_everywhere_and_leaks_nothing(
    client_for, teacher, theirs, their_student, name
):
    client = client_for(teacher)
    for method in (client.get, client.post):
        response = method(reverse(name, args=[theirs.pk]))
        assert response.status_code == 404
        assert b"Secretny" not in response.content and "Секретний".encode() not in response.content
    assert Group.objects.filter(pk=theirs.pk).exists()


def test_foreign_student_is_404(client_for, teacher, their_student):
    client = client_for(teacher)
    url = reverse("people:student_edit", args=[their_student.pk])
    assert client.get(url).status_code == 404
    assert client.post(url, {"full_name": "Hacked"}).status_code == 404
    their_student.refresh_from_db()
    assert their_student.full_name == "Секретний Учень"


def test_missing_pk_is_404(client_for, teacher):
    client = client_for(teacher)
    assert client.get(reverse("people:group", args=[9999])).status_code == 404
    assert client.get(reverse("people:student_edit", args=[9999])).status_code == 404


def test_admin_sees_every_roster(client_for, admin_user, theirs, their_student):
    client = client_for(admin_user)
    assert "8-Б" in client.get(reverse("people:groups")).content.decode()
    assert client.get(reverse("people:group", args=[theirs.pk])).status_code == 200
    assert client.get(reverse("people:student_edit", args=[their_student.pk])).status_code == 200
    page = client.get(reverse("people:students")).content.decode()
    assert "Секретний Учень" in page


def test_csrf_is_enforced_on_every_post(teacher, mine, my_student):
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(teacher)
    for url in (
        reverse("people:group_create"),
        reverse("people:group_edit", args=[mine.pk]),
        reverse("people:group_delete", args=[mine.pk]),
        reverse("people:group_pins", args=[mine.pk]),
        reverse("people:student_create"),
        reverse("people:student_edit", args=[my_student.pk]),
        reverse("people:import"),
        reverse("people:import_confirm"),
    ):
        assert (
            strict.post(url, {"students": "delete", "mode": "all", "confirm": "1"}).status_code
            == 403
        )
    assert Group.objects.filter(pk=mine.pk).exists()
    my_student.refresh_from_db()
    assert my_student.pin == ""


# ---- groups ----------------------------------------------------------------------------------


def test_group_list_shows_my_groups_with_active_counts(client_for, teacher, mine, theirs):
    Student.objects.create(owner=teacher, group=mine, full_name="А Один")
    Student.objects.create(owner=teacher, group=mine, full_name="Б Два", is_active=False)
    Student.objects.create(owner=teacher, full_name="Без Групи")
    ten = Group.objects.create(owner=teacher, name="10-А")
    seven_b = Group.objects.create(owner=teacher, name="7-Б")
    html = client_for(teacher).get(reverse("people:groups")).content.decode()
    assert "8-Б" not in html
    assert html.index("7-А") < html.index("7-Б") < html.index("10-А")  # natural order
    response = client_for(teacher).get(reverse("people:groups"))
    by_name = {g.name: g for g in response.context["groups"]}
    assert (by_name["7-А"].active_count, by_name["7-А"].student_count) == (1, 2)
    assert by_name["10-А"].active_count == 0
    assert response.context["ungrouped_count"] == 1
    assert ten and seven_b


def test_archived_groups_are_hidden_until_asked(client_for, teacher, mine):
    old = Group.objects.create(owner=teacher, name="Минулий рік", is_archived=True)
    client = client_for(teacher)
    html = client.get(reverse("people:groups")).content.decode()
    assert "Минулий рік" not in html and "Show 1 archived group" in html
    html = client.get(reverse("people:groups") + "?archived=1").content.decode()
    assert "Минулий рік" in html and "Hide archived groups" in html
    assert old.is_archived


def test_create_group(client_for, teacher):
    client = client_for(teacher)
    assert client.get(reverse("people:group_create")).status_code == 200
    response = client.post(
        reverse("people:group_create"), {"name": "  7-Б ", "note": "Фізика"}, follow=True
    )
    group = Group.objects.get(owner=teacher)
    assert (group.name, group.note) == ("7-Б", "Фізика")
    assert response.redirect_chain[-1][0] == reverse("people:group", args=[group.pk])
    assert 'Group "7-Б" created.' in messages_of(response)


def test_group_name_must_be_unique_per_teacher_with_a_friendly_error(
    client_for, teacher, other_teacher, mine
):
    client = client_for(teacher)
    for name in ("7-А", "7-а", " 7-А  "):
        response = client.post(reverse("people:group_create"), {"name": name})
        assert response.status_code == 200
        assert "You already have a group with this name." in response.content.decode()
    assert Group.objects.filter(owner=teacher).count() == 1
    # the same name for another teacher is fine
    other = client_for(other_teacher).post(reverse("people:group_create"), {"name": "7-А"})
    assert other.status_code == 302
    assert Group.objects.filter(name="7-А").count() == 2


@pytest.mark.parametrize("name", ["", "   ", "***", "x" * 201])
def test_group_name_validation(client_for, teacher, name):
    response = client_for(teacher).post(reverse("people:group_create"), {"name": name})
    assert response.status_code == 200
    assert Group.objects.count() == 0


def test_edit_and_archive_group(client_for, teacher, mine):
    other = Group.objects.create(owner=teacher, name="7-Б")
    client = client_for(teacher)
    url = reverse("people:group_edit", args=[mine.pk])
    assert "7-А" in client.get(url).content.decode()
    clash = client.post(url, {"name": "7-б", "note": ""})
    assert clash.status_code == 200 and "already have a group" in clash.content.decode()
    ok = client.post(url, {"name": "9-А", "note": "новий", "is_archived": "on"})
    assert ok.status_code == 302
    mine.refresh_from_db()
    assert (mine.name, mine.note, mine.is_archived) == ("9-А", "новий", True)
    # saving with its own name again is not a clash
    assert client.post(url, {"name": "9-А", "note": ""}).status_code == 302
    assert other.name == "7-Б"


def test_group_page_lists_students_with_pins_and_links(client_for, teacher, mine):
    Student.objects.create(owner=teacher, group=mine, full_name="Яременко Оксана", pin="4821")
    Student.objects.create(owner=teacher, group=mine, full_name="Іваненко Петро")
    Student.objects.create(owner=teacher, group=mine, full_name="Пішов Хтось", is_active=False)
    response = client_for(teacher).get(reverse("people:group", args=[mine.pk]))
    html = response.content.decode()
    assert html.index("Іваненко Петро") < html.index("Яременко Оксана")  # alphabet order
    assert "4821" in html and "Left the class" in html
    for name in (
        "people:gradebook",
        "people:group_pins",
        "people:group_edit",
        "people:group_delete",
    ):
        assert reverse(name, args=[mine.pk]) in html
    assert reverse("people:student_create") + f"?group={mine.pk}" in html
    assert reverse("people:import") + f"?group={mine.pk}" in html
    assert "Start a session for this group" in html
    assert (response.context["n_with_pin"], response.context["n_without_pin"]) == (1, 1)


def test_delete_group_page_states_the_consequences(client_for, teacher, mine, my_student):
    html = client_for(teacher).get(reverse("people:group_delete", args=[mine.pk])).content.decode()
    assert "What happens to its 1 student?" in html
    assert 'value="keep"' in html and 'value="delete"' in html
    assert "Attempts are never deleted" in html
    assert Group.objects.filter(pk=mine.pk).exists()  # GET never deletes


def test_delete_group_requires_a_choice(client_for, teacher, mine, my_student):
    response = client_for(teacher).post(reverse("people:group_delete", args=[mine.pk]), {})
    assert response.status_code == 200
    assert "Choose what happens to the students." in response.content.decode()
    assert Group.objects.filter(pk=mine.pk).exists()


def test_delete_group_keeping_students(client_for, teacher, mine, my_student):
    response = client_for(teacher).post(
        reverse("people:group_delete", args=[mine.pk]), {"students": "keep"}, follow=True
    )
    assert response.redirect_chain[-1][0] == reverse("people:groups")
    assert not Group.objects.filter(pk=mine.pk).exists()
    my_student.refresh_from_db()
    assert my_student.group is None
    assert any("kept without a group" in m for m in messages_of(response))


def test_delete_group_with_its_students(client_for, teacher, mine, my_student):
    bystander = Student.objects.create(owner=teacher, full_name="Не Чіпати")
    response = client_for(teacher).post(
        reverse("people:group_delete", args=[mine.pk]), {"students": "delete"}, follow=True
    )
    assert not Group.objects.filter(pk=mine.pk).exists()
    assert not Student.objects.filter(pk=my_student.pk).exists()
    assert Student.objects.filter(pk=bystander.pk).exists()
    assert any("1 student were deleted" in m for m in messages_of(response))


def test_delete_garbage_choice_changes_nothing(client_for, teacher, mine, my_student):
    client_for(teacher).post(reverse("people:group_delete", args=[mine.pk]), {"students": "x"})
    assert (
        Group.objects.filter(pk=mine.pk).exists()
        and Student.objects.filter(pk=my_student.pk).exists()
    )


# ---- PINs ------------------------------------------------------------------------------------


def test_pins_are_never_generated_by_a_get(client_for, teacher, mine, my_student):
    client_for(teacher).get(reverse("people:group_pins", args=[mine.pk]))
    my_student.refresh_from_db()
    assert my_student.pin == ""


def test_generate_missing_pins_keeps_existing_ones(client_for, teacher, mine):
    keep = Student.objects.create(owner=teacher, group=mine, full_name="А Один", pin="4821")
    new = Student.objects.create(owner=teacher, group=mine, full_name="Б Два")
    left = Student.objects.create(owner=teacher, group=mine, full_name="В Три", is_active=False)
    response = client_for(teacher).post(
        reverse("people:group_pins", args=[mine.pk]), {"mode": "missing"}, follow=True
    )
    assert response.redirect_chain[-1][0] == reverse("people:group", args=[mine.pk])
    for student in (keep, new, left):
        student.refresh_from_db()
    assert keep.pin == "4821" and len(new.pin) == 4 and left.pin == ""
    assert "A PIN was set for 1 student." in messages_of(response)

    again = client_for(teacher).post(
        reverse("people:group_pins", args=[mine.pk]), {"mode": "missing"}, follow=True
    )
    assert "Every active student already has a PIN." in messages_of(again)


def test_regenerating_all_pins_asks_first(client_for, teacher, mine):
    one = Student.objects.create(owner=teacher, group=mine, full_name="А Один", pin="4821")
    client = client_for(teacher)
    url = reverse("people:group_pins", args=[mine.pk])

    asked = client.post(url, {"mode": "all"})
    assert asked.status_code == 200
    assert "Regenerate all PINs?" in asked.content.decode()
    one.refresh_from_db()
    assert one.pin == "4821"

    done = client.post(url, {"mode": "all", "confirm": "1"}, follow=True)
    one.refresh_from_db()
    assert one.pin != "4821" and len(one.pin) == 4
    assert "A PIN was set for 1 student." in messages_of(done)


def test_unknown_pin_mode_is_refused(client_for, teacher, mine, my_student):
    response = client_for(teacher).post(
        reverse("people:group_pins", args=[mine.pk]), {"mode": "dance"}, follow=True
    )
    assert "Choose what to do with the PINs." in messages_of(response)
    my_student.refresh_from_db()
    assert my_student.pin == ""


def test_printable_pin_list(client_for, teacher, mine):
    Student.objects.create(owner=teacher, group=mine, full_name="Яременко Оксана", pin="4821")
    Student.objects.create(owner=teacher, group=mine, full_name="Іваненко Петро", pin="9027")
    Student.objects.create(owner=teacher, group=mine, full_name="Немає Піна")
    Student.objects.create(
        owner=teacher, group=mine, full_name="Пішов Хтось", pin="1111", is_active=False
    )
    response = client_for(teacher).get(reverse("people:group_pins", args=[mine.pk]))
    html = response.content.decode()
    assert html.index("Іваненко Петро") < html.index("Яременко Оксана")
    assert "9027" in html and "4821" in html
    assert "Пішов Хтось" not in html and "1111" not in html  # inactive: not printed
    assert "1 student has no PIN yet" in html
    assert "no-print" in html and "people.css" in html


# ---- students --------------------------------------------------------------------------------


def test_student_search_is_case_insensitive_for_cyrillic(client_for, teacher, mine):
    Student.objects.create(owner=teacher, group=mine, full_name="Іваненко Петро")
    Student.objects.create(owner=teacher, group=mine, full_name="Коваль Дем’ян")
    Student.objects.create(owner=teacher, full_name="Мельник Олена")
    client = client_for(teacher)

    def names(**params):
        response = client.get(reverse("people:students"), params)
        return [s.full_name for s in response.context["page"].object_list]

    assert names(q="ІВАН") == ["Іваненко Петро"]
    assert names(q="іваненко") == ["Іваненко Петро"]
    assert names(q="петро іван") == ["Іваненко Петро"]  # any word order
    assert names(q="дем'ян") == ["Коваль Дем’ян"]  # apostrophe variants
    assert names(q="ольга") == []
    assert names(q="  ") == ["Іваненко Петро", "Коваль Дем’ян", "Мельник Олена"]
    assert names(group=str(mine.pk)) == ["Іваненко Петро", "Коваль Дем’ян"]
    assert names(group="none") == ["Мельник Олена"]
    assert names(group="none", q="мельник") == ["Мельник Олена"]
    assert names(group="abc") == ["Іваненко Петро", "Коваль Дем’ян", "Мельник Олена"]


def test_student_list_never_shows_foreign_students_or_groups(
    client_for, teacher, mine, theirs, their_student
):
    client = client_for(teacher)
    response = client.get(reverse("people:students"), {"group": str(theirs.pk)})
    html = response.content.decode()
    assert "Секретний" not in html and "8-Б" not in html
    assert response.context["selected_group"] == ""  # a foreign group id is ignored
    assert (
        "Секретний"
        not in client.get(reverse("people:students"), {"q": "секретний"}).content.decode()
    )


def test_student_list_paginates_and_keeps_the_filters(client_for, teacher, mine):
    Student.objects.bulk_create(
        [
            Student(
                owner=teacher, group=mine, full_name=f"Учень {i:03d}", name_key=f"учень {i:03d}"
            )
            for i in range(120)
        ]
    )
    client = client_for(teacher)
    first = client.get(reverse("people:students"), {"q": "учень"})
    assert len(first.context["page"].object_list) == 50
    html = first.content.decode()
    assert "?q=%D1%83%D1%87%D0%B5%D0%BD%D1%8C&amp;page=2" in html
    last = client.get(reverse("people:students"), {"q": "учень", "page": 3})
    assert len(last.context["page"].object_list) == 20
    assert client.get(reverse("people:students"), {"page": "junk"}).status_code == 200


def test_create_student(client_for, teacher, mine):
    client = client_for(teacher)
    page = client.get(reverse("people:student_create") + f"?group={mine.pk}")
    assert page.context["form"].initial["group"] == mine.pk
    response = client.post(
        reverse("people:student_create"),
        {"full_name": "  Коваль   Дем’ян ", "group": mine.pk, "pin": "4821", "notes": " тихий "},
        follow=True,
    )
    student = Student.objects.get()
    assert (student.full_name, student.group, student.pin, student.notes) == (
        "Коваль Дем’ян",
        mine,
        "4821",
        "тихий",
    )
    assert student.owner == teacher and student.is_active
    assert response.redirect_chain[-1][0] == reverse("people:group", args=[mine.pk])
    assert 'Student "Коваль Дем’ян" added.' in messages_of(response)


def test_create_student_without_a_group_and_add_another(client_for, teacher, mine):
    client = client_for(teacher)
    plain = client.post(reverse("people:student_create"), {"full_name": "Без Групи"})
    assert plain.status_code == 302 and plain["Location"] == reverse("people:students")
    again = client.post(
        reverse("people:student_create"), {"full_name": "Ще Один", "group": mine.pk, "again": "1"}
    )
    assert again["Location"] == reverse("people:student_create") + f"?group={mine.pk}"
    assert Student.objects.count() == 2


def test_create_student_never_accepts_a_foreign_group(client_for, teacher, theirs):
    client = client_for(teacher)
    page = client.get(reverse("people:student_create") + f"?group={theirs.pk}")
    assert page.context["form"].initial == {}
    response = client.post(
        reverse("people:student_create"), {"full_name": "Підміна", "group": theirs.pk}
    )
    assert response.status_code == 200
    assert "group" in response.context["form"].errors
    assert Student.objects.count() == 0


@pytest.mark.parametrize("name", ["", "   ", "12345", "x" * 201])
def test_student_name_validation(client_for, teacher, name):
    response = client_for(teacher).post(reverse("people:student_create"), {"full_name": name})
    assert response.status_code == 200 and Student.objects.count() == 0


@pytest.mark.parametrize("pin", ["12", "abcd", "123456789", "12 34"])
def test_pin_must_be_3_to_8_digits(client_for, teacher, pin):
    response = client_for(teacher).post(
        reverse("people:student_create"), {"full_name": "Іван Петренко", "pin": pin}
    )
    assert response.status_code == 200 and "pin" in response.context["form"].errors


def test_pin_must_be_unique_inside_the_group(client_for, teacher, mine, my_student):
    my_student.pin = "4821"
    my_student.save()
    client = client_for(teacher)
    clash = client.post(
        reverse("people:student_create"),
        {"full_name": "Інший Учень", "group": mine.pk, "pin": "4821"},
    )
    assert clash.status_code == 200
    assert "Another student in this group already has this PIN." in clash.content.decode()
    # the same PIN in another group (or without a group) is fine
    other = Group.objects.create(owner=teacher, name="8-А")
    ok = client.post(
        reverse("people:student_create"),
        {"full_name": "Інший Учень", "group": other.pk, "pin": "4821"},
    )
    assert ok.status_code == 302
    # editing a student keeps its own PIN without a clash
    edit = client.post(
        reverse("people:student_edit", args=[my_student.pk]),
        {"full_name": "Іваненко Петро", "group": mine.pk, "pin": "4821", "is_active": "on"},
    )
    assert edit.status_code == 302


def test_duplicate_warning_needs_an_explicit_add_anyway(client_for, teacher, mine, my_student):
    client = client_for(teacher)
    data = {"full_name": "іваненко  ПЕТРО", "group": mine.pk}
    warned = client.post(reverse("people:student_create"), data)
    assert warned.status_code == 200
    html = warned.content.decode()
    assert "This looks like a student you already have" in html
    assert "Іваненко Петро" in html and 'name="confirm_duplicate"' in html
    assert Student.objects.count() == 1  # nothing saved by the first POST

    done = client.post(reverse("people:student_create"), {**data, "confirm_duplicate": "1"})
    assert done.status_code == 302
    assert Student.objects.count() == 2


def test_duplicate_warning_also_catches_swapped_words_across_groups(
    client_for, teacher, my_student
):
    response = client_for(teacher).post(
        reverse("people:student_create"), {"full_name": "Петро Іваненко"}
    )
    assert response.status_code == 200
    assert "same words in a different order" in response.content.decode()
    assert Student.objects.count() == 1


def test_another_teachers_student_is_not_a_duplicate(client_for, other_teacher, my_student):
    response = client_for(other_teacher).post(
        reverse("people:student_create"), {"full_name": "Іваненко Петро"}
    )
    assert response.status_code == 302
    assert Student.objects.count() == 2


def test_edit_student(client_for, teacher, mine, my_student):
    new_group = Group.objects.create(owner=teacher, name="9-А")
    client = client_for(teacher)
    page = client.get(reverse("people:student_edit", args=[my_student.pk]))
    assert page.status_code == 200 and "Іваненко Петро" in page.content.decode()
    response = client.post(
        reverse("people:student_edit", args=[my_student.pk]),
        {"full_name": "Іваненко Петро-Павло", "group": new_group.pk, "pin": "", "notes": "n"},
    )
    assert response.status_code == 302
    assert response["Location"] == reverse("people:group", args=[new_group.pk])
    my_student.refresh_from_db()
    assert my_student.full_name == "Іваненко Петро-Павло"
    assert my_student.name_key == "іваненко петро-павло"
    assert my_student.group == new_group
    assert my_student.is_active is False  # the checkbox was not ticked
    assert my_student.owner == teacher


def test_edit_student_does_not_nag_when_the_name_is_unchanged(
    client_for, teacher, mine, my_student
):
    Student.objects.create(owner=teacher, group=mine, full_name="Іваненко Петро")  # a known twin
    response = client_for(teacher).post(
        reverse("people:student_edit", args=[my_student.pk]),
        {
            "full_name": "Іваненко Петро",
            "group": mine.pk,
            "notes": "тільки нотатка",
            "is_active": "on",
        },
    )
    assert response.status_code == 302
    my_student.refresh_from_db()
    assert my_student.notes == "тільки нотатка"


def test_edit_student_warns_when_renamed_to_an_existing_name(client_for, teacher, mine, my_student):
    other = Student.objects.create(owner=teacher, group=mine, full_name="Коваль Олена")
    client = client_for(teacher)
    url = reverse("people:student_edit", args=[other.pk])
    data = {"full_name": "Іваненко Петро", "group": mine.pk, "is_active": "on"}
    warned = client.post(url, data)
    assert warned.status_code == 200 and "Save anyway" in warned.content.decode()
    other.refresh_from_db()
    assert other.full_name == "Коваль Олена"
    assert client.post(url, {**data, "confirm_duplicate": "1"}).status_code == 302
    other.refresh_from_db()
    assert other.full_name == "Іваненко Петро"


def test_edit_student_cannot_move_into_a_foreign_group(client_for, teacher, theirs, my_student):
    response = client_for(teacher).post(
        reverse("people:student_edit", args=[my_student.pk]),
        {"full_name": "Іваненко Петро", "group": theirs.pk, "is_active": "on"},
    )
    assert response.status_code == 200 and "group" in response.context["form"].errors
    my_student.refresh_from_db()
    assert my_student.group is not None and my_student.group.owner == teacher


def test_admin_edits_in_the_students_own_roster(client_for, admin_user, teacher, mine, my_student):
    admins_group = Group.objects.create(owner=admin_user, name="Адмін")
    client = client_for(admin_user)
    page = client.get(reverse("people:student_edit", args=[my_student.pk]))
    choices = [group.pk for group in page.context["form"].fields["group"].queryset]
    assert choices == [mine.pk]  # only groups of the student's owner
    bad = client.post(
        reverse("people:student_edit", args=[my_student.pk]),
        {"full_name": "Іваненко Петро", "group": admins_group.pk, "is_active": "on"},
    )
    assert bad.status_code == 200
    created = client.post(
        reverse("people:student_create"), {"full_name": "Новий Учень", "group": mine.pk}
    )
    assert created.status_code == 302
    assert Student.objects.get(full_name="Новий Учень").owner == teacher


def test_next_parameter_only_redirects_to_this_site(client_for, teacher, mine, my_student):
    client = client_for(teacher)
    url = reverse("people:student_edit", args=[my_student.pk])
    data = {"full_name": "Іваненко Петро", "group": mine.pk, "is_active": "on"}
    inside = client.post(url, {**data, "next": reverse("people:students")})
    assert inside["Location"] == reverse("people:students")
    outside = client.post(url, {**data, "next": "https://evil.example/phish"})
    assert outside["Location"] == reverse("people:group", args=[mine.pk])
