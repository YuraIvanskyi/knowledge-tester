"""Placeholder view for URL names that are reserved but not built yet (Phase 6 skeleton).

Each workstream replaces the stub in its own urls module with the real view.
"""

from django.http import HttpResponse


def not_implemented(request, *args, **kwargs):
    return HttpResponse("Not implemented yet.", status=501, content_type="text/plain")
