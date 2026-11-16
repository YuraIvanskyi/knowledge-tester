"""Admin area (/manage/): teacher accounts and system settings (KT-601)."""

from __future__ import annotations

import time

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.db import transaction
from django.db.models import Count
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from apps.assessments.models import Assessment
from apps.core import backup
from apps.delivery.models import Sitting

from . import services
from .forms import (
    ResetPasswordForm,
    SettingsForm,
    TeacherCreateForm,
    TeacherEditForm,
)
from .models import SystemSettings, User
from .permissions import admin_required

# A generated password waits in the server-side session for the very next page view and is
# removed as soon as it is read (or ignored after a few minutes). It is never put in messages
# (those may live in a cookie), logs or the database in any other form.
REVEAL_KEY = "kt_generated_password"
REVEAL_MAX_AGE = 10 * 60


def _remember_generated_password(request, user: User, password: str) -> None:
    request.session[REVEAL_KEY] = {"pk": user.pk, "password": password, "at": time.time()}


def _take_generated_password(request, user: User) -> str | None:
    """Return the generated password waiting for ``user`` (once), and drop whatever is stored."""
    stored = request.session.pop(REVEAL_KEY, None)
    if not stored or stored.get("pk") != user.pk:
        return None
    if time.time() - stored.get("at", 0) > REVEAL_MAX_AGE:
        return None
    return stored.get("password")


def _accounts_with_counts():
    return User.objects.annotate(
        test_count=Count("projects__assessments", distinct=True),
        session_count=Count("sittings", distinct=True),
    )


@admin_required
def home(request):
    teachers = User.objects.filter(role=User.Role.TEACHER)
    settings_row = SystemSettings.load()
    register_url = ""
    if settings_row.allow_registration and settings_row.registration_code:
        register_url = request.build_absolute_uri(reverse("accounts:register"))
    context = {
        "teacher_count": teachers.count(),
        "admin_count": User.objects.filter(role=User.Role.ADMIN).count(),
        "active_count": User.objects.filter(is_active=True).count(),
        "test_count": Assessment.objects.count(),
        "session_count": Sitting.objects.count(),
        "open_session_count": Sitting.objects.filter(status=Sitting.Status.OPEN).count(),
        "settings_row": settings_row,
        "register_url": register_url,
    }
    return render(request, "manage/home.html", context)


@admin_required
def teachers(request):
    query = request.GET.get("q", "").strip()
    accounts = list(_accounts_with_counts().order_by("-is_active", "role", "username"))
    if query:
        # Filtered here, not in SQL: SQLite's LIKE ignores case only for ASCII, so a search for
        # "олена" would miss "Олена". A school has a few dozen teachers at most.
        needle = query.casefold()
        accounts = [
            u for u in accounts if needle in u.username.casefold() or needle in str(u).casefold()
        ]
    return render(
        request, "manage/teachers.html", {"accounts": accounts, "q": query, "me": request.user}
    )


@admin_required
def teacher_create(request):
    form = TeacherCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        messages.success(request, _("Account “%(name)s” created.") % {"name": user.display_name})
        if form.generated:
            _remember_generated_password(request, user, form.new_password)
            return redirect("manage:teacher_password", pk=user.pk)
        return redirect("manage:teachers")
    return render(request, "manage/teacher_create.html", {"form": form})


@admin_required
def teacher_edit(request, pk):
    target = get_object_or_404(_accounts_with_counts(), pk=pk)
    form = TeacherEditForm(request.POST or None, instance=target, acting_user=request.user)
    if request.method == "POST" and form.is_valid():
        # The check in the form ran on data read a moment ago; repeat it inside a transaction so
        # two admins cannot remove each other at the same time.
        with transaction.atomic():
            fresh = User.objects.select_for_update().get(pk=pk)
            error = services.access_change_error(
                fresh,
                acting=request.user,
                new_role=form.cleaned_data["role"],
                new_active=form.cleaned_data["is_active"],
            )
            if error is None:
                # Only these columns: never write back a stale password hash or last_login.
                form.save(commit=False).save(update_fields=["display_name", "role", "is_active"])
        if error is None:
            messages.success(request, _("Changes saved."))
            return redirect("manage:teachers")
        form.add_error(None, error)
    return render(request, "manage/teacher_edit.html", {"form": form, "target": target})


@admin_required
@never_cache
def teacher_password(request, pk):
    target = get_object_or_404(User, pk=pk)
    if request.method == "POST":
        form = ResetPasswordForm(request.POST, user=target)
        if form.is_valid():
            target.set_password(form.new_password)
            target.save(update_fields=["password"])
            if target.pk == request.user.pk:
                update_session_auth_hash(request, target)  # keep the admin logged in
            if form.generated:
                _remember_generated_password(request, target, form.new_password)
                return redirect("manage:teacher_password", pk=target.pk)
            messages.success(
                request, _("The password of “%(name)s” was changed.") % {"name": str(target)}
            )
            return redirect("manage:teachers")
    else:
        form = ResetPasswordForm(user=target)
    generated = _take_generated_password(request, target) if request.method == "GET" else None
    return render(
        request,
        "manage/teacher_password.html",
        {"form": form, "target": target, "generated_password": generated},
    )


@admin_required
@require_POST
def teacher_active(request, pk):
    with transaction.atomic():
        target = get_object_or_404(User.objects.select_for_update(), pk=pk)
        wanted = request.POST.get("active")
        new_active = (not target.is_active) if wanted not in ("0", "1") else wanted == "1"
        error = services.access_change_error(
            target, acting=request.user, new_role=target.role, new_active=new_active
        )
        if error is None and new_active != target.is_active:
            target.is_active = new_active
            target.save(update_fields=["is_active"])
    if error:
        messages.error(request, error)
    elif new_active:
        messages.success(request, _("“%(name)s” can log in again.") % {"name": str(target)})
    else:
        messages.success(
            request,
            _("“%(name)s” can no longer log in. Their data is kept.") % {"name": str(target)},
        )
    return redirect("manage:teachers")


@admin_required
def settings_page(request):
    row = SystemSettings.load()
    data = None
    if request.method == "POST":
        data = request.POST.copy()
        if data.get("action") == "generate_code":
            data["registration_code"] = services.generate_invite_code()
    form = SettingsForm(data, instance=row)
    if request.method == "POST" and form.is_valid():
        form.save()
        if request.POST.get("action") == "generate_code":
            messages.success(request, _("Settings saved with a new invite code."))
        else:
            messages.success(request, _("Settings saved."))
        return redirect("manage:settings")
    register_url = ""
    if row.allow_registration and row.registration_code:
        register_url = request.build_absolute_uri(reverse("accounts:register"))
    return render(request, "manage/settings.html", {"form": form, "register_url": register_url})


# --- backups ------------------------------------------------------------------------------------


@admin_required
def backups(request):
    context = {
        "backups": backup.list_backups(),
        "folder": backup.backup_dir(),
        "keep": backup.KEEP,
        "has_database": backup.database_path() is not None,
    }
    return render(request, "manage/backups.html", context)


@admin_required
@require_POST
def backup_create(request):
    try:
        made = backup.create_backup("manual")
    except backup.BackupError as error:
        messages.error(request, _("The backup failed: %(error)s") % {"error": error})
    else:
        if made is None:
            messages.error(request, _("There is no database file to back up."))
        else:
            messages.success(request, _("Backup “%(name)s” created.") % {"name": made.name})
    return redirect("manage:backups")


@admin_required
def backup_download(request, name: str):
    found = backup.find_backup(name)
    if found is None:
        raise Http404
    return FileResponse(
        found.path.open("rb"),
        as_attachment=True,
        filename=found.name,
        content_type="application/vnd.sqlite3",
    )
