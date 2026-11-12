"""Offline guard for the gradebook pages: no external URLs, nothing the CSP would block."""

import pytest
from django.urls import reverse

from apps.people.tests.gradebook_factories import (
    make_attempt,
    make_group,
    make_sitting,
    make_student,
)
from tests.test_offline import csp_violations, external_urls

pytestmark = pytest.mark.django_db


def gradebook_pages(client, teacher):
    """The page with data, with filters, and the two empty states."""
    full = make_group(teacher, "7-A")
    ann = make_student(teacher, full, "Ann")
    gone = make_student(teacher, full, "Gone", active=False)
    s1 = make_sitting(teacher, group=full, title="Quiz 1")
    s2 = make_sitting(teacher, title="Free names", days=2)
    make_attempt(s1, ann, 85, grade="5")
    make_attempt(s1, ann, 30, pending=1)
    make_attempt(s2, ann, 45, pending=1)
    make_attempt(s2, gone, 20)
    no_students = make_group(teacher, "Empty")
    no_sessions = make_group(teacher, "No sessions")
    make_student(teacher, no_sessions, "Zed")
    urls = [
        reverse("people:gradebook", args=[full.pk]),
        reverse("people:gradebook", args=[full.pk]) + "?since=2026-09-02&project=",
        reverse("people:gradebook", args=[full.pk]) + "?since=2031-01-01",
        reverse("people:gradebook", args=[no_students.pk]),
        reverse("people:gradebook", args=[no_sessions.pk]),
    ]
    return [client.get(url) for url in urls]


def test_gradebook_pages_have_no_external_urls_or_inline_code(client_for, teacher):
    client = client_for(teacher)
    for response in gradebook_pages(client, teacher):
        assert response.status_code == 200
        html = response.content.decode()
        assert external_urls(html) == [], response.request["PATH_INFO"]
        assert csp_violations(html) == [], response.request["PATH_INFO"]
        assert "gradebook.css" in html


def test_gradebook_stylesheet_is_self_contained():
    from pathlib import Path

    css = (Path(__file__).resolve().parent.parent / "static" / "css" / "gradebook.css").read_text(
        encoding="utf-8"
    )
    assert external_urls(css) == []
    assert "@import" not in css and "@font-face" not in css and "url(" not in css
