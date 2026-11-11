from collections import Counter

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from apps.exchange.importer import import_document
from apps.exchange.serializer import export_document

from . import services
from .models import Project

MAX_IMPORT_BYTES = 2 * 1024 * 1024
SAMPLE_PATH = settings.BASE_DIR / "docs" / "examples" / "full.json"

TYPE_LABELS = {
    "single_choice": gettext_lazy("Single choice"),
    "multiple_choice": gettext_lazy("Multiple choice"),
    "choose_n": gettext_lazy("Choose N"),
    "short_answer": gettext_lazy("Short answer"),
    "open": gettext_lazy("Open (manual grading)"),
}


def _owned_assessment(request, pk):
    return get_object_or_404(services.visible_assessments(request.user), pk=pk)


def _question_rows(document: dict) -> list[dict]:
    rows = []
    for number, q in enumerate(document.get("test", {}).get("questions", []), start=1):
        text = q.get("text", "")
        rows.append(
            {
                "number": number,
                "id": q["id"],
                "type": q["type"],
                "type_label": TYPE_LABELS.get(q["type"], q["type"]),
                "points": q.get("points", 1),
                "text": text if len(text) <= 120 else text[:117] + "...",
            }
        )
    return rows


def _summary(document: dict) -> dict:
    test = document["test"]
    questions = test["questions"]
    return {
        "title": test["title"],
        "description": test["description"],
        "language": test["language"],
        "count": len(questions),
        "points": sum(q["points"] for q in questions),
        "types": [(TYPE_LABELS[t], n) for t, n in Counter(q["type"] for q in questions).items()],
        "settings": test["settings"],
        "grading": test["grading"],
    }


@login_required
def test_list(request):
    services.ensure_default_project(request.user)
    projects = list(services.visible_projects(request.user).select_related("owner"))
    assessments = services.visible_assessments(request.user).filter(project__in=projects)
    by_project: dict[int, list] = {p.pk: [] for p in projects}
    for a in assessments:
        by_project[a.project_id].append(a)
    rows = [(p, by_project[p.pk]) for p in projects]
    return render(request, "assessments/list.html", {"rows": rows})


@login_required
def import_test(request):
    default_project = services.ensure_default_project(request.user)
    projects = Project.objects.filter(owner=request.user, is_archived=False)
    context = {
        "text": "",
        "result": None,
        "projects": projects,
        "default_project": default_project,
    }

    if request.method == "POST":
        action = request.POST.get("action", "check")
        text = request.POST.get("document", "")
        upload = request.FILES.get("file")
        if upload is not None:
            if upload.size > MAX_IMPORT_BYTES:
                messages.error(request, _("The file is too large (limit 2 MB)."))
            else:
                text = upload.read().decode("utf-8-sig", errors="replace")
        if action == "sample":
            text = SAMPLE_PATH.read_text(encoding="utf-8")
        elif len(text.encode("utf-8")) > MAX_IMPORT_BYTES:
            messages.error(request, _("The text is too large (limit 2 MB)."))
            text = ""
        context["text"] = text

        if action != "sample":
            if not text.strip():
                messages.error(request, _("Paste the test JSON or choose a file first."))
            else:
                result = import_document(text)
                if action == "create" and result.ok:
                    project = _target_project(request, projects)
                    assessment = services.create_assessment(project, result.document)
                    messages.success(request, _("Test created as a draft. Publish it to use it."))
                    return redirect("assessments:detail", pk=assessment.pk)
                context["result"] = result
                context["report_text"] = (
                    result.report.as_text()
                    if result.report.errors or result.report.warnings
                    else ""
                )
                if result.ok:
                    context["summary"] = _summary(result.document)
    return render(request, "assessments/import.html", context)


def _target_project(request, projects):
    new_title = request.POST.get("new_project", "").strip()
    if new_title:
        return Project.objects.create(owner=request.user, title=new_title[:200])
    chosen = projects.filter(pk=request.POST.get("project") or 0).first()
    return chosen or services.ensure_default_project(request.user)


@login_required
def detail(request, pk):
    assessment = _owned_assessment(request, pk)
    result = import_document(assessment.document)
    context = {
        "assessment": assessment,
        "report": result.report,
        "valid": result.ok,
        "questions": _question_rows(assessment.document),
        "question_types": list(TYPE_LABELS.items()),
        "summary": _summary(result.document) if result.ok else None,
        "revisions": assessment.revisions.all(),
    }
    return render(request, "assessments/detail.html", context)


@login_required
@require_POST
def publish(request, pk):
    assessment = _owned_assessment(request, pk)
    revision, error, created = services.publish(assessment, request.user)
    if error:
        messages.error(request, _("Cannot publish: the test has errors. See the list below."))
    elif created:
        messages.success(request, _("Published as revision %(n)s.") % {"n": revision.number})
    else:
        messages.info(
            request,
            _("Nothing changed since revision %(n)s, so no new revision was created.")
            % {"n": revision.number},
        )
    return redirect("assessments:detail", pk=assessment.pk)


@login_required
def export(request, pk):
    assessment = _owned_assessment(request, pk)
    try:
        body = export_document(assessment.document)
    except ValueError:
        messages.error(request, _("Cannot export: the test has errors."))
        return redirect("assessments:detail", pk=assessment.pk)
    response = HttpResponse(body, content_type="application/json; charset=utf-8")
    filename = f"{slugify(assessment.title) or 'test'}.json"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
