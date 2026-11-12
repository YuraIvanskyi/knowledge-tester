"""The system settings page: school name and the registration switch."""

import re

from django.urls import reverse

from apps.accounts.models import SystemSettings

URL = reverse("manage:settings")


def text(response):
    return response.content.decode()


def test_settings_page_shows_current_values(admin_client):
    row = SystemSettings.load()
    row.school_name = "Lyceum 5"
    row.save()
    html = text(admin_client.get(URL))
    assert 'value="Lyceum 5"' in html
    assert 'name="allow_registration"' in html and 'name="registration_code"' in html
    assert "Registration page:" not in html  # nothing to share while it is off


def test_save_school_name(admin_client):
    response = admin_client.post(URL, {"school_name": "  Lyceum 5  "})
    assert response.status_code == 302 and response["Location"] == URL
    row = SystemSettings.load()
    assert row.school_name == "Lyceum 5"
    assert not row.allow_registration


def test_turn_registration_on_with_a_code(admin_client):
    admin_client.post(
        URL, {"school_name": "", "allow_registration": "on", "registration_code": " school-2026 "}
    )
    row = SystemSettings.load()
    assert row.allow_registration and row.registration_code == "school-2026"
    html = text(admin_client.get(URL))
    assert "Registration page:" in html and reverse("accounts:register") in html
    assert reverse("accounts:register") in text(admin_client.get(reverse("manage:home")))


def test_registration_needs_a_code(admin_client):
    response = admin_client.post(URL, {"allow_registration": "on", "registration_code": ""})
    assert response.status_code == 200
    assert "Set an invite code before turning registration on" in text(response)
    assert not SystemSettings.load().allow_registration


def test_short_code_is_refused(admin_client):
    response = admin_client.post(URL, {"registration_code": "abc"})
    assert response.status_code == 200 and "at least 6 characters" in text(response)
    assert SystemSettings.load().registration_code == ""


def test_generate_code_button(admin_client):
    response = admin_client.post(URL, {"action": "generate_code", "allow_registration": "on"})
    assert response.status_code == 302
    row = SystemSettings.load()
    assert re.fullmatch(r"[A-Z2-9]{4}-[A-Z2-9]{4}", row.registration_code)
    assert row.allow_registration  # the checkbox the admin had ticked is kept
    first = row.registration_code
    admin_client.post(URL, {"action": "generate_code"})
    assert SystemSettings.load().registration_code != first


def test_turn_registration_off_keeps_the_code(admin_client, registration_on):
    admin_client.post(URL, {"registration_code": registration_on})
    row = SystemSettings.load()
    assert not row.allow_registration and row.registration_code == registration_on
    assert admin_client.get(reverse("accounts:register")).status_code == 404
