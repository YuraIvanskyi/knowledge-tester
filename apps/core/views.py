from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render


def landing(request):
    return render(request, "core/landing.html")


@login_required
def dashboard(request):
    return render(request, "core/dashboard.html")


def healthz(request):
    return HttpResponse("ok", content_type="text/plain")
