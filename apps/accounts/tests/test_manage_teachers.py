"""Teacher accounts: list, create, edit, deactivate, and the safety rules."""

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts import services
from apps.accounts.models import User


def new_teacher_data(**extra):
    data = {
        "username": "olena",
        "display_name": "Olena Kovalenko",
        "role": "teacher",
        "password1": "Maple-river-42x",
        "password2": "Maple-river-42x",
    }
    data.update(extra)
    return data


def text(response):
    return response.content.decode()


# --- home and list --------------------------------------------------------------------------


@pytest.mark.django_db
def test_home_shows_counts(admin_client, teacher, other_teacher, published_sitting):
    other_teacher.is_active = False
    other_teacher.save()
    response = admin_client.get(reverse("manage:home"))
    context = response.context
    assert context["teacher_count"] == 2
    assert context["admin_count"] == 1
    assert context["active_count"] == 2  # admin + teacher
    assert context["test_count"] == 1
    assert context["session_count"] == 1
    assert context["open_session_count"] == 1
    html = text(response)
    for name in ("manage:teachers", "manage:settings", "manage:teacher_create"):
        assert reverse(name) in html


def test_list_shows_accounts_with_counts(admin_client, admin_user, teacher, published_sitting):
    response = admin_client.get(reverse("manage:teachers"))
    rows = {u.username: u for u in response.context["accounts"]}
    assert set(rows) == {"admin", "teacher"}
    assert rows["teacher"].test_count == 1
    assert rows["teacher"].session_count == 1
    assert rows["admin"].test_count == 0
    html = text(response)
    assert "teacher" in html and "Never" in html
    assert reverse("manage:teacher_edit", args=[teacher.pk]) in html


def test_list_counts_are_not_inflated_by_joins(admin_client, teacher, published_sitting):
    from apps.delivery import services as delivery

    for n in range(3):
        delivery.create_sitting(
            revision=published_sitting.revision, user=teacher, title=f"extra {n}"
        )
    rows = {u.username: u for u in admin_client.get(reverse("manage:teachers")).context["accounts"]}
    assert rows["teacher"].test_count == 1
    assert rows["teacher"].session_count == 4


def test_list_has_no_toggle_for_yourself(admin_client, admin_user, teacher):
    html = text(admin_client.get(reverse("manage:teachers")))
    assert reverse("manage:teacher_active", args=[teacher.pk]) in html
    assert reverse("manage:teacher_active", args=[admin_user.pk]) not in html


def test_search_by_username_and_by_name(admin_client, django_user_model, teacher):
    django_user_model.objects.create_user(
        "oleksa", password="x", display_name="Олена Коваленко", role="teacher"
    )
    url = reverse("manage:teachers")

    def found(q):
        return {u.username for u in admin_client.get(url, {"q": q}).context["accounts"]}

    assert found("teach") == {"teacher"}
    assert found("TEACH") == {"teacher"}
    assert found("олена") == {"oleksa"}  # case-insensitive for Cyrillic too
    assert found("КОВАЛ") == {"oleksa"}
    assert found("nobody") == set()
    assert "Nobody matches" in text(admin_client.get(url, {"q": "nobody"}))
    assert len(found("")) == 3


# --- create ---------------------------------------------------------------------------------


def test_create_with_typed_password(admin_client, client):
    response = admin_client.post(reverse("manage:teacher_create"), new_teacher_data())
    assert response.status_code == 302
    assert response["Location"] == reverse("manage:teachers")
    user = User.objects.get(username="olena")
    assert user.display_name == "Olena Kovalenko"
    assert user.role == "teacher" and user.is_active
    assert not user.is_staff and not user.is_superuser
    assert user.check_password("Maple-river-42x")
    assert "Maple-river-42x" not in user.password
    assert client.login(username="olena", password="Maple-river-42x")


def test_create_can_make_an_admin(admin_client):
    admin_client.post(reverse("manage:teacher_create"), new_teacher_data(role="admin"))
    assert User.objects.get(username="olena").is_admin_role


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"username": "TEACHER"}, "already taken"),
        ({"username": ""}, "required"),
        ({"username": "bad name!"}, "valid username"),
        ({"display_name": "  "}, "required"),
        ({"password2": "different-Pass-9"}, "do not match"),
        ({"password1": "", "password2": ""}, "Type a password"),
        ({"password1": "short1", "password2": "short1"}, "too short"),
        ({"password1": "12345678901", "password2": "12345678901"}, "entirely numeric"),
        ({"password1": "password123", "password2": "password123"}, "too common"),
        ({"password1": "olena123", "password2": "olena123"}, "too similar"),
        ({"role": "owner"}, "valid choice"),
    ],
)
def test_create_rejects_bad_input(admin_client, teacher, changes, message):
    count = User.objects.count()
    response = admin_client.post(reverse("manage:teacher_create"), new_teacher_data(**changes))
    assert response.status_code == 200
    assert message in text(response)
    assert User.objects.count() == count


def test_create_with_generated_password_is_shown_once(admin_client, client):
    data = new_teacher_data(password1="", password2="", generate="1")
    response = admin_client.post(reverse("manage:teacher_create"), data)
    user = User.objects.get(username="olena")
    assert response.status_code == 302
    assert response["Location"] == reverse("manage:teacher_password", args=[user.pk])
    # Nothing readable travels in the redirect, the cookies or the messages.
    assert not [c for c in response.cookies.values() if "-" in c.value and len(c.value) == 14]

    first = admin_client.get(response["Location"])
    html = text(first)
    assert "only time it is shown" in html and "created" in html
    password = first.context["generated_password"]
    assert password in html and len(password) == 14
    assert "no-store" in first["Cache-Control"] or "private" in first["Cache-Control"]
    assert client.login(username="olena", password=password)
    assert user.password != password  # stored hashed
    user.refresh_from_db()
    assert user.check_password(password) and password not in user.password

    second = admin_client.get(response["Location"])
    assert second.context["generated_password"] is None
    assert password not in text(second)
    assert "kt_generated_password" not in admin_client.session


def test_generated_password_is_not_in_session_after_it_was_shown(admin_client):
    admin_client.post(
        reverse("manage:teacher_create"),
        new_teacher_data(password1="", password2="", generate="1"),
    )
    assert "kt_generated_password" in admin_client.session  # server-side only, until read
    pk = User.objects.get(username="olena").pk
    admin_client.get(reverse("manage:teacher_password", args=[pk]))
    assert "kt_generated_password" not in admin_client.session


def test_generated_passwords_are_random_and_valid():
    seen = {services.generate_password() for _n in range(20)}
    assert len(seen) == 20
    for password in seen:
        services.validate_new_password(password)
        assert len(password) == 14 and password.count("-") == 2
    assert services.generate_invite_code() != services.generate_invite_code()


def test_create_ignores_generate_when_form_is_invalid(admin_client, teacher):
    response = admin_client.post(
        reverse("manage:teacher_create"),
        new_teacher_data(username="teacher", password1="", password2="", generate="1"),
    )
    assert response.status_code == 200 and "already taken" in text(response)
    assert "kt_generated_password" not in admin_client.session


# --- edit -----------------------------------------------------------------------------------


def test_edit_changes_name_role_and_active(admin_client, teacher):
    url = reverse("manage:teacher_edit", args=[teacher.pk])
    response = admin_client.post(url, {"display_name": " Ms Smith ", "role": "admin"})
    assert response.status_code == 302
    teacher.refresh_from_db()
    assert teacher.display_name == "Ms Smith"
    assert teacher.role == "admin"
    assert teacher.is_active is False  # checkbox not sent -> off


def test_edit_cannot_change_username_or_password(admin_client, teacher):
    old_hash = teacher.password
    admin_client.post(
        reverse("manage:teacher_edit", args=[teacher.pk]),
        {
            "display_name": "T",
            "role": "teacher",
            "is_active": "on",
            "username": "renamed",
            "password": "x",
        },
    )
    teacher.refresh_from_db()
    assert teacher.username == "teacher" and teacher.password == old_hash


def test_edit_page_shows_username_as_text(admin_client, teacher):
    html = text(admin_client.get(reverse("manage:teacher_edit", args=[teacher.pk])))
    assert 'name="username"' not in html
    assert "teacher" in html


def test_edit_requires_a_name(admin_client, teacher):
    response = admin_client.post(
        reverse("manage:teacher_edit", args=[teacher.pk]),
        {"display_name": "", "role": "teacher", "is_active": "on"},
    )
    assert response.status_code == 200 and "required" in text(response)


def test_edit_does_not_overwrite_a_newer_password(admin_client, teacher):
    url = reverse("manage:teacher_edit", args=[teacher.pk])
    page = admin_client.get(url)
    assert page.status_code == 200
    teacher.set_password("Changed-meanwhile-7")
    teacher.save()
    admin_client.post(url, {"display_name": "New", "role": "teacher", "is_active": "on"})
    teacher.refresh_from_db()
    assert teacher.check_password("Changed-meanwhile-7") and teacher.display_name == "New"


def test_cannot_demote_or_deactivate_yourself_via_edit(admin_client, admin_user, second_admin):
    url = reverse("manage:teacher_edit", args=[admin_user.pk])
    # Role and active are locked on your own page; posting other values changes nothing.
    html = text(admin_client.get(url))
    assert "You cannot change your own role" in html
    response = admin_client.post(url, {"display_name": "Boss", "role": "teacher"})
    assert response.status_code == 302
    admin_user.refresh_from_db()
    assert admin_user.role == "admin" and admin_user.is_active
    assert admin_user.display_name == "Boss"


def test_superuser_keeps_admin_role(admin_client, second_admin, django_user_model):
    root = django_user_model.objects.create_superuser("root", password="x")
    url = reverse("manage:teacher_edit", args=[root.pk])
    assert "always has the admin role" in text(admin_client.get(url))
    admin_client.post(url, {"display_name": "Root", "role": "teacher", "is_active": "on"})
    root.refresh_from_db()
    assert root.role == "admin"


def test_demoting_another_admin_is_allowed(admin_client, second_admin):
    admin_client.post(
        reverse("manage:teacher_edit", args=[second_admin.pk]),
        {"display_name": "Second", "role": "teacher", "is_active": "on"},
    )
    second_admin.refresh_from_db()
    assert second_admin.role == "teacher"


# --- the safety rules as a service ----------------------------------------------------------


def test_access_change_rules(admin_user, second_admin, teacher):
    check = services.access_change_error
    # yourself
    assert check(admin_user, acting=admin_user, new_role="admin", new_active=False)
    assert check(admin_user, acting=admin_user, new_role="teacher", new_active=True)
    assert check(admin_user, acting=admin_user, new_role="admin", new_active=True) is None
    # someone else, with another admin around
    assert check(second_admin, acting=admin_user, new_role="teacher", new_active=True) is None
    assert check(second_admin, acting=admin_user, new_role="admin", new_active=False) is None
    # a teacher is never "the last admin"
    assert check(teacher, acting=admin_user, new_role="teacher", new_active=False) is None


def test_last_active_admin_cannot_be_removed(admin_user, teacher):
    # Defence in depth: the view guard already makes this unreachable through the UI.
    message = services.access_change_error(
        admin_user, acting=teacher, new_role="teacher", new_active=True
    )
    assert "last active admin" in message
    assert services.access_change_error(
        admin_user, acting=teacher, new_role="admin", new_active=False
    )


def test_inactive_admin_does_not_count_as_a_spare(admin_user, second_admin, teacher):
    second_admin.is_active = False
    second_admin.save()
    assert services.access_change_error(
        admin_user, acting=teacher, new_role="teacher", new_active=True
    )


# --- activate / deactivate ------------------------------------------------------------------


def test_deactivate_and_reactivate(admin_client, teacher, published_sitting):
    url = reverse("manage:teacher_active", args=[teacher.pk])
    victim = Client()
    victim.force_login(teacher)
    assert victim.get(reverse("core:dashboard")).status_code == 200

    response = admin_client.post(url, {"active": "0"})
    assert response.status_code == 302 and response["Location"] == reverse("manage:teachers")
    teacher.refresh_from_db()
    assert not teacher.is_active
    # the open browser session stops working at once
    assert victim.get(reverse("core:dashboard")).status_code == 302
    # data is kept and the session still works for students
    published_sitting.refresh_from_db()
    assert published_sitting.created_by_id == teacher.pk
    taker = Client().get(reverse("taker:session", args=[published_sitting.code]))
    assert taker.status_code == 200

    admin_client.post(url, {"active": "1"})
    teacher.refresh_from_db()
    assert teacher.is_active


def test_active_without_value_toggles(admin_client, teacher):
    url = reverse("manage:teacher_active", args=[teacher.pk])
    admin_client.post(url)
    teacher.refresh_from_db()
    assert not teacher.is_active
    admin_client.post(url)
    teacher.refresh_from_db()
    assert teacher.is_active


def test_cannot_deactivate_yourself(admin_client, admin_user):
    response = admin_client.post(
        reverse("manage:teacher_active", args=[admin_user.pk]), {"active": "0"}, follow=True
    )
    admin_user.refresh_from_db()
    assert admin_user.is_active
    assert "cannot deactivate your own account" in text(response)


def test_can_deactivate_another_admin(admin_client, second_admin):
    admin_client.post(reverse("manage:teacher_active", args=[second_admin.pk]), {"active": "0"})
    second_admin.refresh_from_db()
    assert not second_admin.is_active


def test_deactivated_teacher_cannot_log_in(admin_client, teacher, client, password):
    admin_client.post(reverse("manage:teacher_active", args=[teacher.pk]), {"active": "0"})
    login_url = reverse("accounts:login")
    inactive = client.post(login_url, {"username": "teacher", "password": password})
    assert inactive.status_code == 200
    wrong = client.post(login_url, {"username": "teacher", "password": "not-the-password"})
    unknown = client.post(login_url, {"username": "nobody", "password": "whatever-1"})

    def alert(response):
        html = text(response)
        start = html.index("alert-bad")
        return html[start : html.index("</div>", start)]

    # the same message in all three cases: the page does not reveal that the account exists
    assert alert(inactive) == alert(wrong) == alert(unknown)
    assert "inactive" not in text(inactive).lower()
    assert "_auth_user_id" not in client.session


# --- passwords ------------------------------------------------------------------------------


def test_reset_with_typed_password(admin_client, teacher, client):
    url = reverse("manage:teacher_password", args=[teacher.pk])
    response = admin_client.post(
        url, {"password1": "Brand-new-pw-81", "password2": "Brand-new-pw-81"}
    )
    assert response.status_code == 302 and response["Location"] == reverse("manage:teachers")
    teacher.refresh_from_db()
    assert teacher.check_password("Brand-new-pw-81")
    assert client.login(username="teacher", password="Brand-new-pw-81")
    assert "kt_generated_password" not in admin_client.session


@pytest.mark.parametrize(
    "data, message",
    [
        ({"password1": "", "password2": ""}, "Type a password"),
        ({"password1": "Brand-new-pw-81", "password2": "Brand-new-pw-82"}, "do not match"),
        ({"password1": "abc", "password2": "abc"}, "too short"),
        ({"password1": "teacher123", "password2": "teacher123"}, "similar"),
        ({"password1": "qwerty12345", "password2": "qwerty12345"}, "too common"),
    ],
)
def test_reset_validates_typed_password(admin_client, teacher, data, message):
    old = teacher.password
    response = admin_client.post(reverse("manage:teacher_password", args=[teacher.pk]), data)
    assert response.status_code == 200 and message in text(response)
    teacher.refresh_from_db()
    assert teacher.password == old


def test_reset_with_generated_password(admin_client, teacher, client, password):
    url = reverse("manage:teacher_password", args=[teacher.pk])
    response = admin_client.post(url, {"generate": "1"})
    assert response.status_code == 302 and response["Location"] == url
    page = admin_client.get(url)
    generated = page.context["generated_password"]
    assert generated and generated in text(page)
    assert not client.login(username="teacher", password=password)  # old one is gone
    assert client.login(username="teacher", password=generated)
    again = admin_client.get(url)
    assert generated not in text(again)


def test_generated_password_is_only_shown_for_its_own_account(admin_client, teacher, other_teacher):
    admin_client.post(reverse("manage:teacher_password", args=[teacher.pk]), {"generate": "1"})
    wrong_page = admin_client.get(reverse("manage:teacher_password", args=[other_teacher.pk]))
    assert wrong_page.context["generated_password"] is None
    # ... and it was dropped for good by that visit
    right_page = admin_client.get(reverse("manage:teacher_password", args=[teacher.pk]))
    assert right_page.context["generated_password"] is None


def test_generated_password_expires(admin_client, teacher, monkeypatch):
    from apps.accounts import manage_views

    url = reverse("manage:teacher_password", args=[teacher.pk])
    admin_client.post(url, {"generate": "1"})
    real_time = manage_views.time.time
    monkeypatch.setattr(manage_views.time, "time", lambda: real_time() + 3600)
    assert admin_client.get(url).context["generated_password"] is None


def test_post_does_not_reveal_the_password(admin_client, teacher):
    """The POST answers with a redirect only; the secret is not in its body."""
    response = admin_client.post(
        reverse("manage:teacher_password", args=[teacher.pk]), {"generate": "1"}
    )
    assert response.status_code == 302 and not response.content


def test_resetting_your_own_password_keeps_you_logged_in(admin_client, admin_user):
    url = reverse("manage:teacher_password", args=[admin_user.pk])
    admin_client.post(url, {"password1": "Brand-new-pw-81", "password2": "Brand-new-pw-81"})
    assert admin_client.get(reverse("manage:home")).status_code == 200
    admin_user.refresh_from_db()
    assert admin_user.check_password("Brand-new-pw-81")


def test_resetting_someone_elses_password_logs_them_out(admin_client, teacher):
    victim = Client()
    victim.force_login(teacher)
    assert victim.get(reverse("core:dashboard")).status_code == 200
    admin_client.post(
        reverse("manage:teacher_password", args=[teacher.pk]),
        {"password1": "Brand-new-pw-81", "password2": "Brand-new-pw-81"},
    )
    assert victim.get(reverse("core:dashboard")).status_code == 302


def test_password_can_be_reset_for_an_inactive_account(admin_client, teacher):
    teacher.is_active = False
    teacher.save()
    response = admin_client.post(
        reverse("manage:teacher_password", args=[teacher.pk]),
        {"password1": "Brand-new-pw-81", "password2": "Brand-new-pw-81"},
    )
    assert response.status_code == 302
    teacher.refresh_from_db()
    assert teacher.check_password("Brand-new-pw-81") and not teacher.is_active


def test_fallback_validators_apply_when_settings_have_none(settings):
    settings.AUTH_PASSWORD_VALIDATORS = []
    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        services.validate_new_password("short")
    settings.AUTH_PASSWORD_VALIDATORS = [
        {
            "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
            "OPTIONS": {"min_length": 3},
        }
    ]
    services.validate_new_password("abc")  # the project's own list wins when it is set
