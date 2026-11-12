"""Skeleton checks: name normalisation, model basics and the ownership helpers."""

import pytest
from django.db import IntegrityError
from django.http import Http404

from apps.people import access
from apps.people.models import Group, Student
from apps.people.names import name_tokens, normalize_name, same_person_key


def test_normalize_name_unifies_case_space_and_apostrophes():
    assert normalize_name("  Дем’ян   КОВАЛЬ ") == "дем'ян коваль"
    assert normalize_name("Дем'ян Коваль") == normalize_name("Демʼян Коваль")
    assert normalize_name("Anna-Maria  O.Brien") == "anna-maria o brien"
    assert normalize_name("") == ""
    assert normalize_name(None) == ""


def test_same_person_key_ignores_word_order():
    assert same_person_key("Іваненко Петро") == same_person_key("петро  іваненко")
    assert name_tokens("Іваненко Петро") == ["іваненко", "петро"]


@pytest.mark.django_db
def test_student_save_fills_name_key(teacher):
    student = Student.objects.create(owner=teacher, full_name="  Іван   Петренко ")
    assert student.name_key == "іван петренко"
    student.full_name = "Олена Коваль"
    student.save(update_fields=["full_name"])
    student.refresh_from_db()
    assert student.name_key == "олена коваль"


@pytest.mark.django_db
def test_group_name_is_unique_per_owner(teacher, other_teacher):
    Group.objects.create(owner=teacher, name="7-A")
    Group.objects.create(owner=other_teacher, name="7-A")
    with pytest.raises(IntegrityError):
        Group.objects.create(owner=teacher, name="7-A")


@pytest.mark.django_db
def test_deleting_group_keeps_students(teacher):
    group = Group.objects.create(owner=teacher, name="7-A")
    student = Student.objects.create(owner=teacher, group=group, full_name="Іван Петренко")
    group.delete()
    student.refresh_from_db()
    assert student.group is None


@pytest.mark.django_db
def test_access_helpers_scope_by_owner(teacher, other_teacher, admin_user):
    mine = Group.objects.create(owner=teacher, name="7-A")
    theirs = Group.objects.create(owner=other_teacher, name="8-B")
    s_mine = Student.objects.create(owner=teacher, group=mine, full_name="A B")
    s_theirs = Student.objects.create(owner=other_teacher, group=theirs, full_name="C D")
    assert list(access.groups_for(teacher)) == [mine]
    assert set(access.groups_for(admin_user)) == {mine, theirs}
    assert list(access.students_for(teacher)) == [s_mine]
    assert access.can_manage_student(teacher, s_mine)
    assert not access.can_manage_student(teacher, s_theirs)
    assert access.can_manage_group(admin_user, theirs)
    with pytest.raises(Http404):
        access.get_group_or_404(teacher, theirs.pk)
