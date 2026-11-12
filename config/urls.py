from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("i18n/", include("django.conf.urls.i18n")),
    path("accounts/", include("apps.accounts.urls")),
    path("teach/tests/", include("apps.assessments.urls")),
    path("teach/sessions/", include("apps.delivery.urls")),
    path("teach/people/", include("apps.people.urls")),
    path("teach/results/", include("apps.reports.urls")),
    path("manage/", include("apps.accounts.manage_urls")),
    path("s/", include("apps.delivery.taker_urls")),
    path("", include("apps.core.urls")),
]
