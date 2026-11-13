"""Roster pages: groups, students, PIN sheets and the import wizard (KT-602).

Every view needs a login and goes through `apps.people.access`, so a foreign pk is a 404.
Everything that changes data is a POST; the confirm pages (delete group, regenerate PINs, import)
show first and act only on the POST that follows.
"""

from __future__ import annotations

import secrets

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Count, Max, Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.views.decorators.http import require_http_methods, require_POST

from . import importing, services
from .access import get_group_or_404, get_student_or_404, groups_for, students_for
from .forms import GroupForm, ImportForm, StudentForm
from .models import Group
from .names import normalize_name

PAGE_SIZE = 50
SESSION_KEY = "roster_import"
MAX_PASTE_KEPT = 200_000  # characters of pasted text kept for "edit the list"
# A POST may carry at most 1000 fields (DATA_UPLOAD_MAX_NUMBER_FIELDS): bigger previews have no
# per-row checkboxes and import every valid row.
MAX_CHECKBOX_ROWS = 800


def _query_group(request, name: str = "group") -> Group | None:
    """A group named in the query string, only if the user may manage it (else ignored)."""
    value = request.GET.get(name, "")
    if not value.isdecimal() or len(value) > 18:  # isdigit() admits "²", which int() rejects
        return None
    return groups_for(request.user).filter(pk=int(value)).first()


def _safe_next(request, fallback: str) -> str:
    target = request.POST.get("next") or request.GET.get("next") or ""
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts=None):
        return target
    return fallback


def _group_url(group: Group | None) -> str:
    return reverse("people:group", args=[group.pk]) if group else reverse("people:students")


# ---- groups --------------------------------------------------------------------------------


@login_required
def group_list(request):
    show_archived = request.GET.get("archived") == "1"
    annotated = groups_for(request.user).select_related("owner")
    annotated = annotated.annotate(
        active_count=Count("students", filter=Q(students__is_active=True), distinct=True),
        student_count=Count("students", distinct=True),
        last_session=Max("sittings__created_at"),
    )
    archived_count = annotated.filter(is_archived=True).count()
    if not show_archived:
        annotated = annotated.filter(is_archived=False)
    rows = sorted(annotated, key=lambda g: services.natural_group_key(g.name))
    return render(
        request,
        "people/roster/groups.html",
        {
            "groups": rows,
            "show_archived": show_archived,
            "archived_count": archived_count,
            "ungrouped_count": students_for(request.user).filter(group__isnull=True).count(),
            "total_students": students_for(request.user).count(),
        },
    )


@login_required
def group_create(request):
    form = GroupForm(
        request.POST if request.method == "POST" else None,
        owner=request.user,
    )
    if request.method == "POST" and form.is_valid():
        try:
            group = services.create_group(
                request.user,
                name=form.cleaned_data["name"],
                note=form.cleaned_data["note"],
            )
        except services.GroupNameTaken:
            form.add_error("name", _("You already have a group with this name."))
        else:
            messages.success(request, _('Group "%(name)s" created.') % {"name": group.name})
            return redirect("people:group", pk=group.pk)
    return render(request, "people/roster/group_form.html", {"form": form, "group": None})


@login_required
def group_detail(request, pk):
    group = get_group_or_404(request.user, pk)
    students = services.sort_students(group.students.all())
    active = [s for s in students if s.is_active]
    return render(
        request,
        "people/roster/group.html",
        {
            "group": group,
            "students": students,
            "n_active": len(active),
            "n_inactive": len(students) - len(active),
            "n_with_pin": sum(1 for s in active if s.pin),
            "n_without_pin": sum(1 for s in active if not s.pin),
            "n_sessions": group.sittings.count(),
        },
    )


@login_required
def group_edit(request, pk):
    group = get_group_or_404(request.user, pk)
    title = group.name
    form = GroupForm(
        request.POST if request.method == "POST" else None,
        instance=group,
        owner=group.owner,
    )
    if request.method == "POST" and form.is_valid():
        try:
            services.update_group(
                group,
                name=form.cleaned_data["name"],
                note=form.cleaned_data["note"],
                is_archived=form.cleaned_data["is_archived"],
            )
        except services.GroupNameTaken:
            form.add_error("name", _("You already have a group with this name."))
        else:
            messages.success(request, _("Group saved."))
            return redirect("people:group", pk=group.pk)
    return render(
        request, "people/roster/group_form.html", {"form": form, "group": group, "title": title}
    )


@login_required
@require_http_methods(["GET", "HEAD", "POST"])
def group_delete(request, pk):
    group = get_group_or_404(request.user, pk)
    impact = services.group_impact(group)
    error = ""
    if request.method == "POST":
        choice = request.POST.get("students")
        if choice not in ("keep", "delete"):
            error = _("Choose what happens to the students.")
        else:
            name = group.name
            deleted = services.delete_group(group, delete_students=choice == "delete")
            if deleted:
                messages.success(
                    request,
                    ngettext(
                        'Group "%(name)s" and its %(n)s student were deleted.',
                        'Group "%(name)s" and its %(n)s students were deleted.',
                        deleted,
                    )
                    % {"name": name, "n": deleted},
                )
            else:
                messages.success(
                    request,
                    _('Group "%(name)s" deleted. Its students are kept without a group.')
                    % {"name": name},
                )
            return redirect("people:groups")
    return render(
        request,
        "people/roster/group_delete.html",
        {"group": group, "impact": impact, "error": error},
    )


# ---- PINs ----------------------------------------------------------------------------------


@login_required
@require_http_methods(["GET", "HEAD", "POST"])
def group_pins(request, pk):
    """GET: the printable PIN list. POST: generate (missing) or regenerate (all, confirmed)."""
    group = get_group_or_404(request.user, pk)
    if request.method == "POST":
        mode = request.POST.get("mode")
        if mode == "missing":
            count = services.generate_pins(group)
        elif mode == "all":
            if request.POST.get("confirm") != "1":
                return render(
                    request,
                    "people/roster/pins_confirm.html",
                    {
                        "group": group,
                        "n_with_pin": group.students.filter(is_active=True).exclude(pin="").count(),
                    },
                )
            count = services.generate_pins(group, regenerate=True)
        else:
            messages.error(request, _("Choose what to do with the PINs."))
            return redirect("people:group", pk=group.pk)
        if count:
            messages.success(
                request,
                ngettext(
                    "A PIN was set for %(n)s student.",
                    "PINs were set for %(n)s students.",
                    count,
                )
                % {"n": count},
            )
        else:
            messages.info(request, _("Every active student already has a PIN."))
        return redirect("people:group", pk=group.pk)

    students = [s for s in services.sort_students(group.students.all()) if s.is_active]
    return render(
        request,
        "people/roster/pins_list.html",
        {
            "group": group,
            "students": students,
            "n_without_pin": sum(1 for s in students if not s.pin),
        },
    )


# ---- students ------------------------------------------------------------------------------


@login_required
def student_list(request):
    user = request.user
    my_groups = sorted(
        groups_for(user).select_related("owner"), key=lambda g: services.natural_group_key(g.name)
    )
    query = request.GET.get("q", "").strip()
    group_filter = request.GET.get("group", "")

    qs = students_for(user).select_related("owner")
    selected_group = ""
    if group_filter == "none":
        qs = qs.filter(group__isnull=True)
        selected_group = "none"
    elif (
        group_filter.isdecimal()
        and len(group_filter) <= 18
        and any(g.pk == int(group_filter) for g in my_groups)
    ):
        qs = qs.filter(group_id=int(group_filter))
        selected_group = group_filter
    for token in normalize_name(query).split():
        # name_key is case-folded in Python; SQLite would only fold ASCII on its own.
        qs = qs.filter(name_key__contains=token)

    ordered = services.sort_students(qs)
    page = Paginator(ordered, PAGE_SIZE).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return render(
        request,
        "people/roster/students.html",
        {
            "page": page,
            "groups": my_groups,
            "q": query,
            "selected_group": selected_group,
            "querystring": params.urlencode(),
            "filtered": bool(query or selected_group),
            "show_owner": user.is_admin_role,
        },
    )


def _duplicate_context(duplicates) -> list[dict]:
    return [{"student": d.student, "kind": d.kind} for d in duplicates]


@login_required
def student_create(request):
    user = request.user
    initial_group = _query_group(request)
    posted = request.method == "POST"
    form = StudentForm(
        request.POST if posted else None,
        user=user,
        initial={"group": initial_group.pk} if initial_group else None,
    )
    duplicates = []
    if posted and form.is_valid():
        data = form.cleaned_data
        group = data["group"]
        owner = group.owner if group else user
        duplicates = services.find_duplicates(owner, data["full_name"])
        if not duplicates or request.POST.get("confirm_duplicate") == "1":
            student = services.create_student(
                owner,
                full_name=data["full_name"],
                group=group,
                pin=data["pin"],
                notes=data["notes"],
            )
            messages.success(request, _('Student "%(name)s" added.') % {"name": student.full_name})
            if request.POST.get("again") == "1":
                target = reverse("people:student_create")
                return redirect(f"{target}?group={group.pk}" if group else target)
            return redirect(_group_url(group))
    return render(
        request,
        "people/roster/student_form.html",
        {
            "form": form,
            "student": None,
            "duplicates": _duplicate_context(duplicates),
            "back_url": _group_url(initial_group),
        },
    )


@login_required
def student_edit(request, pk):
    student = get_student_or_404(request.user, pk)
    name_shown, old_key = student.full_name, student.name_key
    fallback_url = _group_url(student.group)  # before validation touches the instance
    posted = request.method == "POST"
    form = StudentForm(request.POST if posted else None, instance=student, user=request.user)
    duplicates = []
    if posted and form.is_valid():
        data = form.cleaned_data
        # Only a changed name can create a new duplicate; do not nag on every save.
        if normalize_name(data["full_name"]) != old_key:
            duplicates = services.find_duplicates(
                student.owner, data["full_name"], exclude_pk=student.pk
            )
        if not duplicates or request.POST.get("confirm_duplicate") == "1":
            services.update_student(
                student,
                full_name=data["full_name"],
                group=data["group"],
                pin=data["pin"],
                notes=data["notes"],
                is_active=data["is_active"],
            )
            messages.success(request, _("Student saved."))
            return redirect(_safe_next(request, _group_url(student.group)))  # the new group
    return render(
        request,
        "people/roster/student_form.html",
        {
            "form": form,
            "student": student,
            "student_name": name_shown,
            "duplicates": _duplicate_context(duplicates),
            "back_url": _safe_next(request, fallback_url),
            "next": request.GET.get("next", ""),
        },
    )


# ---- import --------------------------------------------------------------------------------


def _stored_import(request):
    return request.session.get(SESSION_KEY)


def _stored_rows(data) -> list[importing.ParsedRow]:
    return [importing.ParsedRow.from_dict(item) for item in data.get("rows", [])]


def _stored_default_group(request, data) -> tuple[Group | None, bool]:
    """(group, ok). ok is False when a group was chosen but is gone or no longer allowed."""
    pk = data.get("default_group")
    if not pk:
        return None, True
    group = groups_for(request.user).filter(pk=pk).first()
    return group, group is not None


@login_required
def import_start(request):
    """Step 1: paste a list or upload a file. Step 2 (`?step=preview`): check the result."""
    if request.GET.get("step") == "preview":
        return _import_preview(request)

    user = request.user
    initial = {}
    group = _query_group(request)
    if group:
        initial["default_group"] = group.pk
    stored = _stored_import(request)
    if request.GET.get("back") == "1" and stored:
        initial.update(
            text=stored.get("text") or "",
            new_group=stored.get("new_group") or "",
            default_group=stored.get("default_group") or initial.get("default_group"),
        )

    posted = request.method == "POST"
    form = ImportForm(
        request.POST if posted else None,
        request.FILES if posted else None,
        user=user,
        initial=initial,
    )
    if posted and form.is_valid():
        upload = form.cleaned_data["file"]
        try:
            if upload is not None:
                rows = importing.parse_file(upload.read(importing.MAX_BYTES + 1))
                source, text = "file", ""
            else:
                text = form.cleaned_data["text"]
                rows = importing.parse_text(text)
                source = "paste"
        except importing.RosterImportError as error:
            form.add_error(None, str(error))
        else:
            if not rows:
                form.add_error(None, _("No names were found in this list."))
            else:
                default_group = form.cleaned_data["default_group"]
                request.session[SESSION_KEY] = {
                    "token": secrets.token_hex(8),
                    "rows": [row.to_dict() for row in rows],
                    "default_group": default_group.pk if default_group else None,
                    "new_group": importing.clean(form.cleaned_data["new_group"]),
                    "source": source,
                    "text": text if len(text) <= MAX_PASTE_KEPT else "",
                }
                return redirect(f"{reverse('people:import')}?step=preview")
    return render(
        request, "people/roster/import.html", {"form": form, "limit_rows": importing.MAX_ROWS}
    )


def _import_preview(request):
    data = _stored_import(request)
    if not data:
        messages.info(request, _("There is nothing to check. Start with a list."))
        return redirect("people:import")
    default_group, ok = _stored_default_group(request, data)
    if not ok:
        messages.error(request, _("The chosen group no longer exists. Start again."))
        return redirect("people:import")
    rows = _stored_rows(data)
    preview = services.build_preview(request.user, rows, default_group, data.get("new_group", ""))
    return render(
        request,
        "people/roster/import_preview.html",
        {
            "preview": preview,
            "token": data["token"],
            "default_group": default_group,
            "new_group_name": data.get("new_group", ""),
            "selectable": len(rows) <= MAX_CHECKBOX_ROWS,
            "n_addable": preview.n_new + preview.n_duplicate,
            "can_edit": data.get("source") == "paste",
        },
    )


def _result_messages(request, result: services.ImportResult) -> None:
    parts = [
        ngettext("%(n)s student added.", "%(n)s students added.", result.created)
        % {"n": result.created}
    ]
    if result.groups_created:
        parts.append(
            ngettext("%(n)s group created.", "%(n)s groups created.", result.groups_created)
            % {"n": result.groups_created}
        )
    messages.success(request, " ".join(parts))

    skipped = []
    if result.skipped_duplicates:
        skipped.append(
            ngettext(
                "%(n)s duplicate skipped.",
                "%(n)s duplicates skipped.",
                result.skipped_duplicates,
            )
            % {"n": result.skipped_duplicates}
        )
    if result.skipped_invalid:
        skipped.append(
            ngettext(
                "%(n)s row that is not valid was skipped.",
                "%(n)s rows that are not valid were skipped.",
                result.skipped_invalid,
            )
            % {"n": result.skipped_invalid}
        )
    if result.skipped_unticked:
        skipped.append(
            ngettext(
                "%(n)s row you unticked was skipped.",
                "%(n)s rows you unticked were skipped.",
                result.skipped_unticked,
            )
            % {"n": result.skipped_unticked}
        )
    if skipped:
        messages.info(request, " ".join(skipped))


@login_required
@require_POST
def import_confirm(request):
    data = _stored_import(request)
    if not data or not secrets.compare_digest(
        str(data.get("token", "")), request.POST.get("token", "")
    ):
        messages.error(request, _("This preview is out of date. Start the import again."))
        return redirect("people:import")
    default_group, ok = _stored_default_group(request, data)
    if not ok:
        messages.error(request, _("The chosen group no longer exists. Start again."))
        return redirect("people:import")

    rows = _stored_rows(data)
    selected = None
    if len(rows) <= MAX_CHECKBOX_ROWS:
        selected = {
            int(v) for v in request.POST.getlist("include") if v.isdecimal() and len(v) <= 18
        }
    preview_url = f"{reverse('people:import')}?step=preview"
    try:
        result = services.apply_import(
            request.user,
            rows,
            default_group,
            data.get("new_group", ""),
            selected=selected,
            skip_duplicates=request.POST.get("skip_duplicates") == "1",
        )
    except IntegrityError:
        messages.error(request, _("Could not save the list. Please try again."))
        return redirect(preview_url)

    if not result.created:
        messages.warning(
            request,
            _("Nothing was added: every row is unticked, a duplicate or not valid."),
        )
        return redirect(preview_url)

    request.session.pop(SESSION_KEY, None)
    _result_messages(request, result)
    if result.group is not None:
        return redirect("people:group", pk=result.group.pk)
    if result.groups_used:
        return redirect("people:groups")
    return redirect("people:students")
