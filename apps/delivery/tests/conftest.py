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


# --- class sessions (KT-603 / KT-604) ----------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_cache():
    """The PIN throttle lives in the cache: every test starts with no recorded failures."""
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


def make_student(owner, group, name, pin="", **extra):
    from apps.people.models import Student

    return Student.objects.create(owner=owner, group=group, full_name=name, pin=pin, **extra)


@pytest.fixture
def group(teacher):
    from apps.people.models import Group

    return Group.objects.create(owner=teacher, name="7-A")


@pytest.fixture
def pupils(teacher, group):
    """Ann (PIN 5829), Bob (PIN 7314), Cleo (no PIN), Dan (left the class), one other class."""
    from apps.people.models import Group

    other_group = Group.objects.create(owner=teacher, name="7-B")
    return {
        "ann": make_student(teacher, group, "Ann Lee", pin="5829", notes="SECRET-NOTE"),
        "bob": make_student(teacher, group, "Bob Ray", pin="7314"),
        "cleo": make_student(teacher, group, "Cleo Fox"),
        "dan": make_student(teacher, group, "Dan Gone", pin="9065", is_active=False),
        "eve": make_student(teacher, other_group, "Eve Stone", pin="1357"),
    }


@pytest.fixture
def group_sitting(teacher, revision, group, pupils):
    return services.create_sitting(revision=revision, user=teacher, title="7-A", group=group)


@pytest.fixture
def pin_sitting(teacher, revision, group, pupils):
    return services.create_sitting(
        revision=revision, user=teacher, title="7-A", group=group, use_pin=True
    )


def pick(client, sitting, student, **extra):
    """POST the Start form of a class session (the no-JavaScript path)."""
    return client.post(f"/s/{sitting.code}/", {"student": student.pk, **extra})
