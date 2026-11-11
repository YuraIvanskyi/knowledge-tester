"""Shared pytest fixtures."""

import pytest
from django.urls import NoReverseMatch, reverse

PASSWORD = "pw-for-tests-123"


def url_names_resolve(*names: str) -> bool:
    """True if every URL name can be reversed (other workstreams' views may not exist yet).

    Names that need arguments are tried with pk=1.
    """
    for name in names:
        for kwargs in ({}, {"pk": 1}, {"revision_pk": 1}, {"sitting_pk": 1}):
            try:
                reverse(name, kwargs=kwargs)
                break
            except NoReverseMatch:
                continue
        else:
            return False
    return True


@pytest.fixture
def password():
    return PASSWORD


@pytest.fixture
def teacher(django_user_model):
    return django_user_model.objects.create_user("teacher", password=PASSWORD, role="teacher")


@pytest.fixture
def other_teacher(django_user_model):
    return django_user_model.objects.create_user("teacher2", password=PASSWORD, role="teacher")


@pytest.fixture
def admin_user(django_user_model):
    return django_user_model.objects.create_superuser("admin", password=PASSWORD)


@pytest.fixture
def client_for(client):
    """Return a callable that logs the shared test client in as the given user."""

    def _login(user):
        client.force_login(user)
        return client

    return _login


@pytest.fixture
def teacher_client(client_for, teacher):
    return client_for(teacher)
