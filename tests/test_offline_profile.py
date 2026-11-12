"""Offline and CSP guard for the student profile pages (KT-605)."""

from pathlib import Path

import pytest
from django.urls import reverse

from apps.delivery.models import Attempt
from apps.people.tests.profile_factory import (
    make_attempt,
    make_group,
    make_project,
    make_revision,
    make_sitting,
    make_student,
)
from tests.test_offline import csp_violations, external_urls

pytestmark = pytest.mark.django_db

STATIC_CSS = Path(__file__).resolve().parent.parent / "static" / "css" / "profile.css"


@pytest.fixture
def pages(teacher_client, teacher):
    group = make_group(teacher)
    student = make_student(teacher, group=group, pin="1234", notes="<i>x</i>")
    empty = make_student(teacher, "Порожній Профіль")
    sitting = make_sitting(make_revision(make_project(teacher)), teacher)
    make_attempt(sitting, student, percent="75.0", days=1, grade="4")
    make_attempt(sitting, student, percent="60.0", days=2, pending=1)
    make_attempt(sitting, student, status=Attempt.Status.VOIDED)
    make_attempt(sitting, student, status=Attempt.Status.IN_PROGRESS)
    urls = [
        reverse("people:student", args=[student.pk]),
        reverse("people:student", args=[empty.pk]),
        reverse("people:student_delete", args=[student.pk]),
        reverse("people:student_delete", args=[empty.pk]),
    ]
    responses = [teacher_client.get(url) for url in urls]
    # the notes form re-rendered with an error
    responses.append(
        teacher_client.post(
            reverse("people:student_notes", args=[student.pk]), {"notes": "я" * 2500}
        )
    )
    return responses


def test_profile_pages_have_no_external_urls_or_inline_code(pages):
    assert len(pages) == 5
    for response in pages:
        html = response.content.decode()
        assert response.status_code in (200, 400)
        assert external_urls(html) == [], response.request["PATH_INFO"]
        assert csp_violations(html) == [], response.request["PATH_INFO"]


def test_profile_pages_load_their_stylesheet_and_no_script(pages):
    for response in pages:
        html = response.content.decode()
        assert "/static/css/profile.css" in html
        assert "<script" not in html  # no JavaScript is needed on these pages


def test_profile_css_is_local_and_small():
    text = STATIC_CSS.read_text(encoding="utf-8")
    assert external_urls(text) == []
    assert "@import" not in text and "@font-face" not in text and "url(" not in text
    assert STATIC_CSS.stat().st_size < 6 * 1024
