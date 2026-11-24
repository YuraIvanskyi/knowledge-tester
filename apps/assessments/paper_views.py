"""The test as a printable PDF for a written (paper) test (F-07)."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect
from django.utils.http import content_disposition_header
from django.utils.translation import gettext as _

from apps.exchange import variants as test_variants
from apps.exchange.importer import import_document
from apps.reports import paper_pdf as paper

from .views import _owned_assessment


@login_required
def paper_pdf(request, pk):
    """GET with the options of `paper.PaperOptions.from_query` (variant, copies, key, paper).

    Prints the test as it is now in the editor, published or not, as long as it is valid."""
    assessment = _owned_assessment(request, pk)  # ownership first: another teacher gets a 404
    result = import_document(assessment.document)
    if not result.ok:
        messages.error(request, _("Cannot print: the test has errors. See the list below."))
        return redirect("assessments:detail", pk=assessment.pk)
    test = result.document["test"]
    options = paper.PaperOptions.from_query(request.GET, test_variants.variant_ids(test))
    response = HttpResponse(paper.render_paper(test, options), content_type="application/pdf")
    response["Content-Disposition"] = content_disposition_header(
        False, paper.filename(test, options)
    )
    return response
