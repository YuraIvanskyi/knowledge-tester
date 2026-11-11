"""Test-only urlconf: the real one plus a stub for reports URLs that may not exist yet."""

from django.http import HttpResponse
from django.urls import include, path

from config.urls import urlpatterns as real_patterns

stub_reports = (
    [
        path("session/<int:sitting_pk>/", lambda r, sitting_pk: HttpResponse("r"), name="session"),
        path("attempt/<int:pk>/", lambda r, pk: HttpResponse("r"), name="attempt"),
    ],
    "reports",
)

urlpatterns = [p for p in real_patterns if getattr(p.pattern, "_route", "") != "teach/results/"] + [
    path("teach/results/", include(stub_reports))
]
