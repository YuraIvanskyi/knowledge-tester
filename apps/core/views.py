from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from apps.assessments.models import Assessment
from apps.assessments.services import with_latest_revision
from apps.delivery.models import Sitting
from apps.people import access as people_access

from . import prompts

RECENT = 5


def landing(request):
    if request.user.is_authenticated:
        return redirect("core:dashboard")
    return render(request, "core/landing.html")


@login_required
def dashboard(request):
    user = request.user
    tests = Assessment.objects.select_related("project")
    sittings = Sitting.objects.select_related("revision__assessment")
    if not user.is_admin_role:
        tests = tests.filter(project__owner=user)
        sittings = sittings.filter(created_by=user)
    open_sittings = sittings.filter(status=Sitting.Status.OPEN)
    context = {
        "test_count": tests.count(),
        "open_count": open_sittings.count(),
        "session_count": sittings.count(),
        "group_count": people_access.groups_for(user).filter(is_archived=False).count(),
        "student_count": people_access.students_for(user).filter(is_active=True).count(),
        "recent_tests": with_latest_revision(tests).order_by("-updated_at")[:RECENT],
        "open_sessions": open_sittings.annotate(attempt_count=Count("attempts"))[:RECENT],
    }
    return render(request, "core/dashboard.html", context)


@login_required
def help_page(request):
    """Prompts to copy into a chat AI (test from a textbook), so nobody has to look for them
    in the program folder."""
    pack = prompts.textbook_prompt()
    return render(
        request,
        "core/help.html",
        {"pack": pack, "path": pack.path, "import_url": reverse("assessments:import")},
    )


def healthz(request):
    return HttpResponse("ok", content_type="text/plain")
