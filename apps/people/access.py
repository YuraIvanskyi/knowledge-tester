"""Ownership rules for people data. EVERY view and service that reads groups or students
must go through these helpers, so teachers only ever see their own (admins see everything)."""

from __future__ import annotations

from django.shortcuts import get_object_or_404

from .models import Group, Student


def groups_for(user):
    qs = Group.objects.all()
    return qs if user.is_admin_role else qs.filter(owner=user)


def students_for(user):
    qs = Student.objects.select_related("group")
    return qs if user.is_admin_role else qs.filter(owner=user)


def can_manage_group(user, group: Group) -> bool:
    return user.is_authenticated and (user.is_admin_role or group.owner_id == user.pk)


def can_manage_student(user, student: Student) -> bool:
    return user.is_authenticated and (user.is_admin_role or student.owner_id == user.pk)


def get_group_or_404(user, pk: int) -> Group:
    return get_object_or_404(groups_for(user), pk=pk)


def get_student_or_404(user, pk: int) -> Student:
    return get_object_or_404(students_for(user), pk=pk)


__all__ = [
    "can_manage_group",
    "can_manage_student",
    "get_group_or_404",
    "get_student_or_404",
    "groups_for",
    "students_for",
]
