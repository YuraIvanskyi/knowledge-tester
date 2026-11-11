import copy

import pytest
from django.test import Client
from django.urls import NoReverseMatch, reverse

from apps.assessments.models import Assessment, Project, Revision
from apps.delivery import services

DOCUMENT = {
    "format": "knowledge-tester/test",
    "version": 1,
    "test": {
        "title": "Fractions",
        "description": "Quick check.",
        "language": "en",
        "settings": {
            "time_limit_minutes": 10,
            "shuffle_questions": True,
            "shuffle_options": True,
            "one_question_per_page": False,
            "show_result": "score",
            "max_attempts": 1,
        },
        "taker_fields": [
            {"key": "name", "label": "Full name", "required": True},
            {"key": "class", "label": "Class", "required": False},
        ],
        "grading": {"enabled": True, "scale": "percent"},
        "questions": [
            {
                "id": "q1",
                "type": "single_choice",
                "text": "Which fraction equals 0.5?",
                "points": 1,
                "required": True,
                "options": [
                    {"id": "a", "text": "one half", "correct": True},
                    {"id": "b", "text": "one third"},
                    {"id": "c", "text": "two thirds"},
                ],
            },
            {
                "id": "q2",
                "type": "multiple_choice",
                "text": "Select every fraction greater than 1/2.",
                "points": 2,
                "scoring": "partial",
                "options": [
                    {"id": "a", "text": "three quarters", "correct": True},
                    {"id": "b", "text": "two thirds", "correct": True},
                    {"id": "c", "text": "one quarter"},
                    {"id": "d", "text": "two fifths"},
                ],
            },
            {
                "id": "q3",
                "type": "choose_n",
                "text": "Choose the 2 fractions equal to 1/2.",
                "points": 2,
                "n": 2,
                "options": [
                    {"id": "a", "text": "two fourths", "correct": True},
                    {"id": "b", "text": "three sixths", "correct": True},
                    {"id": "c", "text": "two thirds"},
                    {"id": "d", "text": "three fourths"},
                ],
            },
            {
                "id": "q4",
                "type": "short_answer",
                "text": "Write 3/4 as a decimal.",
                "points": 1,
                "mode": "text",
                "accept": ["ZEBRA-ACCEPT"],
            },
            {
                "id": "q5",
                "type": "open",
                "text": "Explain how to compare fractions.",
                "points": 3,
                "rubric": "SECRET-RUBRIC",
            },
        ],
    },
}


def make_document(**settings) -> dict:
    doc = copy.deepcopy(DOCUMENT)
    doc["test"]["settings"].update(settings)
    return doc


def make_revision(owner, document=None, title="Fractions") -> Revision:
    project = Project.objects.create(owner=owner, title="P")
    doc = document or make_document()
    assessment = Assessment.objects.create(project=project, title=title, document=doc)
    return Revision.objects.create(
        assessment=assessment, number=1, document=doc, content_hash="x", created_by=owner
    )


@pytest.fixture
def teacher(django_user_model):
    return django_user_model.objects.create_user("teacher", password="pw")


@pytest.fixture
def other_teacher(django_user_model):
    return django_user_model.objects.create_user("other", password="pw")


@pytest.fixture
def admin_user(django_user_model):
    return django_user_model.objects.create_user("boss", password="pw", role="admin")


@pytest.fixture
def revision(teacher):
    return make_revision(teacher)


@pytest.fixture
def sitting(teacher, revision):
    return services.create_sitting(revision=revision, user=teacher, title="7-A")


@pytest.fixture
def make_sitting(teacher):
    def factory(**settings):
        revision = make_revision(teacher, make_document(**settings))
        return services.create_sitting(revision=revision, user=teacher, title="S")

    return factory


@pytest.fixture
def grade_calls(monkeypatch):
    """Spy on the grading call while still running the real grader."""
    import apps.grading.service as grading

    calls = []
    real = grading.grade_attempt

    def spy(attempt):
        calls.append(attempt.pk)
        return real(attempt)

    monkeypatch.setattr(grading, "grade_attempt", spy)
    return calls


@pytest.fixture
def taker_client():
    return Client()


@pytest.fixture(autouse=True)
def _reports_urls_available(settings):
    """Teacher templates link to reports:session (workstream B). Stub it until it exists."""
    try:
        reverse("reports:session", args=[1])
    except NoReverseMatch:
        settings.ROOT_URLCONF = "apps.delivery.tests.stub_urls"


def start(client, sitting, name="Ann Lee", **extra):
    data = {"tf_name": name, **extra}
    return client.post(f"/s/{sitting.code}/", data)
