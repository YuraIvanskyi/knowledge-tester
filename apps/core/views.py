from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import redirect, render

from apps.assessments.models import Assessment
from apps.delivery.models import Sitting

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
        "recent_tests": tests.order_by("-updated_at")[:RECENT],
        "open_sessions": open_sittings.annotate(attempt_count=Count("attempts"))[:RECENT],
    }
    return render(request, "core/dashboard.html", context)


def healthz(request):
    return HttpResponse("ok", content_type="text/plain")
