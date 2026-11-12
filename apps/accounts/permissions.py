"""Access guard for the admin area (/manage/)."""

from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.http import Http404


def admin_required(view):
    """Anonymous -> login page; a logged-in non-admin -> 404 (the area is not advertised).

    Put it outermost, above ``require_POST`` and friends, so that a teacher probing a POST-only
    URL with GET still sees 404 and not 405.
    """

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not (user.is_active and user.is_admin_role):
            raise Http404
        return view(request, *args, **kwargs)

    return wrapper
