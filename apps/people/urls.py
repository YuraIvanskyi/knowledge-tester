"""People URLs (prefix /teach/people/). Frozen: each workstream owns its own module."""

from . import urls_gradebook, urls_profile, urls_roster

app_name = "people"

urlpatterns = [
    *urls_roster.urlpatterns,
    *urls_profile.urlpatterns,
    *urls_gradebook.urlpatterns,
]
