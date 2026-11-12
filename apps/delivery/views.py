"""Teacher side of delivery: manage sessions, the share screen and linking attempts to students."""

import segno
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.views.decorators.http import require_POST

from apps.assessments.models import Revision
from apps.core import lan
from apps.people.access import students_for

from . import linking, roster, services
from .forms import SittingForm
from .models import Attempt, Sitting


def _own_sitting(request, pk: int) -> Sitting:
    sitting = get_object_or_404(
        Sitting.objects.select_related("revision__assessment", "group"), pk=pk
    )
    if not services.can_manage(request.user, sitting):
        raise Http404
    return sitting


@login_required
def session_list(request):
    sittings = Sitting.objects.select_related("revision__assessment", "group").annotate(
        attempt_count=Count("attempts")
    )
    if not request.user.is_admin_role:
        sittings = sittings.filter(created_by=request.user)
    return render(request, "delivery/list.html", {"sittings": sittings})


@login_required
def session_create(request, revision_pk: int):
    revision = get_object_or_404(
        Revision.objects.select_related("assessment__project"), pk=revision_pk
    )
    if not (request.user.is_admin_role or revision.assessment.project.owner_id == request.user.pk):
        raise Http404
    test = revision.test
    if request.method == "POST":
        form = SittingForm(request.POST, user=request.user)
        if form.is_valid():
            sitting = services.create_sitting(
                revision=revision,
                user=request.user,
                title=form.cleaned_data["title"],
                access_code=form.cleaned_data["access_code"].strip(),
                group=form.cleaned_data["group"],
                use_pin=form.cleaned_data["use_pin"],
            )
            _warn_about_roster(request, sitting)
            return redirect("delivery:share", pk=sitting.pk)
    else:
        form = SittingForm(
            initial={"title": test.get("title") or revision.assessment.title}, user=request.user
        )
    context = {
        "form": form,
        "revision": revision,
        "test": test,
        "time_limit": services.time_limit_minutes(test),
        "question_count": len(test.get("questions", [])),
    }
    return render(request, "delivery/create.html", context)


def _warn_about_roster(request, sitting: Sitting) -> None:
    """Right after creating a class session: say who cannot take part yet."""
    if not sitting.group_id:
        return
    info = roster.group_summary(sitting)
    if not info["students"]:
        messages.warning(
            request,
            _("This class has no active students yet. Add students before you share the link."),
        )
    elif sitting.use_pin and info["no_pin"]:
        messages.warning(
            request,
            ngettext(
                "%(n)d student of this class has no PIN yet and cannot be picked in this session. "
                "Generate PINs on the class page.",
                "%(n)d students of this class have no PIN yet and cannot be picked in this "
                "session. Generate PINs on the class page.",
                info["no_pin"],
            )
            % {"n": info["no_pin"]},
        )


def _qr_svg(url: str) -> str:
    qr = segno.make(url, error="m")
    return mark_safe(  # noqa: S308 - segno output contains no user-controlled markup
        qr.svg_inline(scale=1, omitsize=True, border=2, dark="#000000", light="#ffffff")
    )


@login_required
def session_share(request, pk: int):
    sitting = _own_sitting(request, pk)
    addresses = lan.lan_ipv4_addresses()
    chosen = request.GET.get("ip")
    if chosen in addresses:
        request.session["share_ip"] = chosen
    chosen = request.session.get("share_ip")
    if chosen in addresses:
        base = f"http://{chosen}:{request.get_port()}"
    else:
        chosen = addresses[0] if addresses else ""
        base = lan.base_url(request)
    url = f"{base}/s/{sitting.code}/"
    stats = services.session_stats(sitting)
    context = {
        "sitting": sitting,
        "url": url,
        "qr_svg": _qr_svg(url),
        "addresses": addresses if len(addresses) > 1 else [],
        "chosen_ip": chosen,
        "stats": stats,
        "is_open": sitting.status == Sitting.Status.OPEN,
        "group_info": roster.group_summary(sitting) if sitting.group_id else None,
    }
    return render(request, "delivery/share.html", context)


@login_required
def session_stats(request, pk: int):
    sitting = _own_sitting(request, pk)
    response = JsonResponse(services.session_stats(sitting))
    response["Cache-Control"] = "no-store"
    return response


@login_required
@require_POST
def session_reopen(request, pk: int):
    sitting = _own_sitting(request, pk)
    if services.reopen_sitting(sitting):
        messages.success(
            request, _("Session reopened. Students can join again with the same link and code.")
        )
    return redirect("delivery:share", pk=sitting.pk)


@login_required
def session_delete(request, pk: int):
    sitting = _own_sitting(request, pk)
    if request.method == "POST":
        services.delete_sitting(sitting)
        messages.success(request, _("Session deleted."))
        return redirect("delivery:list")
    return render(
        request,
        "delivery/confirm_delete.html",
        {"sitting": sitting, "attempt_count": sitting.attempts.count()},
    )


@login_required
@require_POST
def session_close(request, pk: int):
    sitting = _own_sitting(request, pk)
    count = services.close_sitting(sitting)
    messages.success(
        request,
        _("Session closed. %(count)d unfinished attempt(s) were submitted automatically.")
        % {"count": count},
    )
    return redirect("delivery:share", pk=sitting.pk)


# --- linking attempts to students (KT-604) -----------------------------------------------------


def _kind_label(kind: str) -> str:
    return {
        linking.EXACT: _("same name"),
        linking.WORDS: _("same words"),
        linking.FUZZY: _("similar"),
    }[kind]


def _link_option_groups(pool, session_group_id):
    """The teacher's students for the select, grouped by class: the session's class first."""
    by_group: dict[int | None, list] = {}
    for student in pool:
        by_group.setdefault(student.group_id, []).append(student)
    names = {s.group_id: s.group.name for s in pool if s.group_id}

    def order(group_id):
        if group_id is None:
            return (2, ())
        if group_id == session_group_id:
            return (0, ())
        return (1, roster.name_sort_key(names[group_id]))

    result = []
    for group_id in sorted(by_group, key=order):
        students = sorted(by_group[group_id], key=lambda s: roster.name_sort_key(s.full_name))
        result.append({"label": names.get(group_id) or _("No class"), "students": students})
    return result


def _link_rows(sitting, attempts, pool, fields):
    indexed = linking.index_students(pool)
    pool_ids = {s.pk for s in pool}
    rows = []
    for attempt in attempts:
        typed = (attempt.taker or {}).get("name", "")
        found = [
            s for s in linking.suggest_indexed(typed, indexed) if s.student.pk != attempt.student_id
        ]
        if attempt.student_id:
            selected = attempt.student_id
        else:
            chosen = linking.preselected(found, sitting.group_id)
            selected = chosen.pk if chosen else None
        suggestions = [
            {
                "student": s.student,
                "percent": s.percent,
                "label": _kind_label(s.kind),
                "confident": s.confident,
            }
            for s in found
        ]
        rows.append(
            {
                "attempt": attempt,
                "typed": services.taker_display(attempt, fields),
                "student": attempt.student,
                "selected": selected,
                "suggestions": suggestions,
                "suggested_pks": {s["student"].pk for s in suggestions},
                # A linked student who is inactive now is still offered, so saving keeps the link.
                "current_extra": attempt.student
                if attempt.student_id and attempt.student_id not in pool_ids
                else None,
            }
        )
    # Unlinked first (they need a decision), then by typed name.
    rows.sort(key=lambda r: (r["attempt"].student_id is not None, roster.name_sort_key(r["typed"])))
    return rows


def _posted_choices(post, attempts) -> dict[int, int | None]:
    choices: dict[int, int | None] = {}
    for attempt in attempts:
        key = f"student_{attempt.pk}"
        if key not in post:
            continue  # not on the page that was submitted: leave it alone
        raw = post.get(key, "").strip()
        if not raw:
            choices[attempt.pk] = None
            continue
        student_id = roster.parse_student_id(raw)
        if student_id is None:
            raise services.LinkError(raw)
        choices[attempt.pk] = student_id
    return choices


@login_required
def session_link(request, pk: int):
    """Link the session's attempts to students after the fact (GET: table, POST: apply all)."""
    sitting = _own_sitting(request, pk)
    # Only the session owner's active students (an admin acts for the owner). Any other
    # student id fails validation in services.apply_links.
    pool = list(students_for(request.user).filter(owner_id=sitting.created_by_id, is_active=True))
    attempts = list(
        sitting.attempts.exclude(status=Attempt.Status.VOIDED).select_related("student__group")
    )
    status = 200
    error = ""
    if request.method == "POST":
        try:
            changed = services.apply_links(
                attempts, _posted_choices(request.POST, attempts), {s.pk: s for s in pool}
            )
        except services.LinkError:
            status = 400
            error = _(
                "One of the chosen students is not available (any more). "
                "Nothing was saved. Check the list and try again."
            )
        else:
            if changed:
                messages.success(
                    request,
                    ngettext(
                        "Saved: %(n)d attempt updated.",
                        "Saved: %(n)d attempts updated.",
                        changed,
                    )
                    % {"n": changed},
                )
            else:
                messages.info(request, _("Nothing to change."))
            return redirect("delivery:link", pk=sitting.pk)
    rows = _link_rows(sitting, attempts, pool, services.taker_fields(sitting.revision.test))
    context = {
        "sitting": sitting,
        "rows": rows,
        "option_groups": _link_option_groups(pool, sitting.group_id),
        "total": len(rows),
        "linked": sum(1 for r in rows if r["attempt"].student_id),
        "no_students": not pool,
        "error": error,
    }
    return render(request, "delivery/link.html", context, status=status)
