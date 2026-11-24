"""The test as a printable PDF for a written (paper) test. Skeleton: the body is not built yet."""

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse

from .views import _owned_assessment


@login_required
def paper_pdf(request, pk):
    _owned_assessment(request, pk)  # ownership first: another teacher gets a 404
    return HttpResponse("Not implemented yet.", content_type="text/plain")
