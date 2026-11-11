"""Teacher side of delivery: manage sessions and the share screen."""

import segno
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.assessments.models import Revision
from apps.core import lan

from . import services
from .forms import SittingForm
from .models import Sitting


def _own_sitting(request, pk: int) -> Sitting:
    sitting = get_object_or_404(Sitting.objects.select_related("revision__assessment"), pk=pk)
    if not services.can_manage(request.user, sitting):
        raise Http404
    return sitting


@login_required
def session_list(request):
    sittings = Sitting.objects.select_related("revision__assessment").annotate(
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
        form = SittingForm(request.POST)
        if form.is_valid():
            sitting = services.create_sitting(
                revision=revision,
                user=request.user,
                title=form.cleaned_data["title"],
                access_code=form.cleaned_data["access_code"].strip(),
            )
            return redirect("delivery:share", pk=sitting.pk)
    else:
        form = SittingForm(initial={"title": test.get("title") or revision.assessment.title})
    context = {
        "form": form,
        "revision": revision,
        "test": test,
        "time_limit": services.time_limit_minutes(test),
        "question_count": len(test.get("questions", [])),
    }
    return render(request, "delivery/create.html", context)


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
def session_close(request, pk: int):
    sitting = _own_sitting(request, pk)
    count = services.close_sitting(sitting)
    messages.success(
        request,
        _("Session closed. %(count)d unfinished attempt(s) were submitted automatically.")
        % {"count": count},
    )
    return redirect("delivery:share", pk=sitting.pk)
