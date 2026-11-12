"""Fixtures for the admin-area tests."""

import pytest
from django.core.cache import cache
from django.test import Client

STRONG = "Maple-river-42x"  # passes Django's validators


@pytest.fixture(autouse=True)
def _fresh_cache():
    """Throttle counters live in the cache; never let one test leak into the next."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def strong_password():
    return STRONG


@pytest.fixture
def admin_client(admin_user):
    client = Client()
    client.force_login(admin_user)
    return client


@pytest.fixture
def teacher_c(teacher):
    client = Client()
    client.force_login(teacher)
    return client


@pytest.fixture
def anon_client():
    return Client()


@pytest.fixture
def second_admin(django_user_model):
    return django_user_model.objects.create_user("admin2", password=STRONG, role="admin")


@pytest.fixture
def registration_on():
    """Turn self-registration on and return the invite code."""
    from apps.accounts.models import SystemSettings

    row = SystemSettings.load()
    row.allow_registration = True
    row.registration_code = "OPEN-SESAME"
    row.save()
    return row.registration_code


@pytest.fixture
def published_sitting(teacher):
    """An open session created by `teacher`."""
    from apps.assessments import editing, services
    from apps.delivery import services as delivery

    document = editing.blank_document("Quick check", "en")
    editing.add_question(
        document, {"id": "q1", "type": "open", "text": "Explain", "points": 1, "required": False}
    )
    project = services.ensure_default_project(teacher)
    assessment = services.create_assessment(project, document)
    revision, error, _created = services.publish(assessment, teacher)
    assert error is None
    return delivery.create_sitting(revision=revision, user=teacher, title="Class 7")
