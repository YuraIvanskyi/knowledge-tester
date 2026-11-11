from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("teach/tests/", include("apps.assessments.urls")),
    path("teach/sessions/", include("apps.delivery.urls")),
    path("teach/results/", include("apps.reports.urls")),
    path("s/", include("apps.delivery.taker_urls")),
    path("", include("apps.core.urls")),
]
