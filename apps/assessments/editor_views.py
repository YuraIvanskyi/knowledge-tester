"""Browser editor for draft tests: create, settings, questions (plain forms, no JavaScript)."""

import copy

from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import translation
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from . import editing, services
from .models import Project
from .views import TYPE_LABELS, _owned_assessment


def _question_or_404(document: dict, question_id: str) -> tuple[int, dict]:
    found = editing.find_question(document, question_id)
    if found is None:
        raise Http404("No such question")
    return found


def _type_or_404(question_type: str) -> str:
    if question_type not in editing.QUESTION_TYPES:
        raise Http404("Unknown question type")
    return question_type


@login_required
def create(request):
    """Start a new empty test."""
    default_project = services.ensure_default_project(request.user)
    projects = Project.objects.filter(owner=request.user, is_archived=False)
    error = ""
    title = ""
    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        if not title:
            error = _("Give the test a title.")
        else:
            new_project = request.POST.get("new_project", "").strip()
            if new_project:
                project = Project.objects.create(owner=request.user, title=new_project[:200])
            else:
                project = (
                    projects.filter(pk=request.POST.get("project") or 0).first() or default_project
                )
            language = translation.get_language() or django_settings.LANGUAGE_CODE
            document = editing.blank_document(title[:200], language.split("-")[0])
            assessment = services.create_assessment(project, document)
            messages.success(request, _("Test created. Add the first question."))
            return redirect("assessments:detail", pk=assessment.pk)
    return render(
        request,
        "assessments/editor/create.html",
        {"projects": projects, "default_project": default_project, "title": title, "error": error},
    )


@login_required
def test_settings(request, pk):
    assessment = _owned_assessment(request, pk)
    document = copy.deepcopy(assessment.document)
    test = document.setdefault("test", {})
    errors: list[str] = []
    if request.method == "POST":
        form = editing.settings_form_from_post(request.POST)
        if request.POST.get("action") == "add_field":
            form["taker_fields"].append({"key": "", "label": "", "required": False})
        else:
            updated, errors = editing.apply_settings(test, form)
            if updated is not None:
                document["test"] = updated
                services.save_draft(assessment, document)
                messages.success(request, _("Settings saved."))
                return redirect("assessments:detail", pk=assessment.pk)
    else:
        form = editing.settings_form(test)
    return render(
        request,
        "assessments/editor/settings.html",
        {
            "assessment": assessment,
            "form": form,
            "errors": errors,
            "languages": django_settings.LANGUAGES,
            "show_results": editing.SHOW_RESULTS,
            "scales": [*editing.GRADE_SCALES, *(["custom"] if form["scale"] == "custom" else [])],
        },
    )


def _question_page(request, assessment, document, question_type, question_id, form, errors, is_new):
    return render(
        request,
        "assessments/editor/question.html",
        {
            "assessment": assessment,
            "type": question_type,
            "type_label": TYPE_LABELS[question_type],
            "is_choice": question_type in ("single_choice", "multiple_choice", "choose_n"),
            "question_id": question_id,
            "number": (
                len(editing.questions_of(document)) + 1
                if is_new
                else _question_or_404(document, question_id)[0] + 1
            ),
            "is_new": is_new,
            "form": form,
            "errors": errors,
        },
    )


def _handle_question(request, assessment, question_type, question_id, is_new):
    document = copy.deepcopy(assessment.document)
    if is_new:
        question_id = editing.next_question_id(document)
    else:
        _index, existing = _question_or_404(document, question_id)
        question_type = existing["type"]
    errors: list[str] = []

    if request.method != "POST":
        form = editing.blank_form(question_type) if is_new else editing.form_from_question(existing)
        return _question_page(
            request, assessment, document, question_type, question_id, form, errors, is_new
        )

    form = editing.form_from_post(request.POST, question_type)
    if request.POST.get("action") == "add_option":
        editing.pad_options(form, len(form["options"]) + 1)
        return _question_page(
            request, assessment, document, question_type, question_id, form, errors, is_new
        )

    question, errors = editing.build_question(form, question_type, question_id)
    if question is None:
        editing.pad_options(form, editing.MIN_OPTION_ROWS if is_new else len(form["options"]))
        return _question_page(
            request, assessment, document, question_type, question_id, form, errors, is_new
        )

    if is_new:
        editing.add_question(document, question)
    else:
        editing.replace_question(document, question_id, question)
    services.save_draft(assessment, document)
    messages.success(request, _("Question saved."))
    if request.POST.get("action") == "save_add" and is_new:
        return redirect("assessments:question_new", pk=assessment.pk, question_type=question_type)
    return redirect("assessments:detail", pk=assessment.pk)


@login_required
def question_new(request, pk, question_type):
    assessment = _owned_assessment(request, pk)
    return _handle_question(request, assessment, _type_or_404(question_type), None, True)


@login_required
def question_edit(request, pk, question_id):
    assessment = _owned_assessment(request, pk)
    return _handle_question(request, assessment, None, question_id, False)


@login_required
def question_delete(request, pk, question_id):
    assessment = _owned_assessment(request, pk)
    document = copy.deepcopy(assessment.document)
    index, question = _question_or_404(document, question_id)
    if request.method == "POST":
        editing.delete_question(document, question_id)
        services.save_draft(assessment, document)
        messages.success(request, _("Question deleted."))
        return redirect("assessments:detail", pk=assessment.pk)
    return render(
        request,
        "assessments/editor/confirm_delete.html",
        {"assessment": assessment, "number": index + 1, "question": question},
    )


@login_required
@require_POST
def question_move(request, pk, question_id):
    assessment = _owned_assessment(request, pk)
    document = copy.deepcopy(assessment.document)
    _question_or_404(document, question_id)
    if editing.move_question(document, question_id, request.POST.get("direction", "")):
        services.save_draft(assessment, document)
    return redirect("assessments:detail", pk=assessment.pk)


@login_required
@require_POST
def question_duplicate(request, pk, question_id):
    assessment = _owned_assessment(request, pk)
    document = copy.deepcopy(assessment.document)
    _question_or_404(document, question_id)
    editing.duplicate_question(document, question_id)
    services.save_draft(assessment, document)
    messages.success(request, _("Question duplicated."))
    return redirect("assessments:detail", pk=assessment.pk)
