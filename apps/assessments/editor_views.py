"""Browser editor for draft tests: create, settings, questions (plain forms, no JavaScript)."""

import copy

from django.conf import settings as django_settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import translation
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.delivery.taker_views import render_preview
from apps.exchange import variants as test_variants
from apps.exchange.importer import import_document

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
                project = services.chosen_project(projects, request.POST.get("project"))
                project = project or default_project
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


def _question_page(
    request, assessment, document, question_type, question_id, form, errors, is_new, variant=""
):
    test = document.get("test") or {}
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
                len(editing.questions_of(document, variant)) + 1
                if is_new
                else _question_or_404(document, question_id)[0] + 1
            ),
            "variant": variant,
            "variant_label": test_variants.label(test, variant),
            "is_new": is_new,
            "form": form,
            "errors": errors,
        },
    )


def _handle_question(request, assessment, question_type, question_id, is_new):
    document = copy.deepcopy(assessment.document)
    test = document.get("test") or {}
    if is_new:
        question_id = editing.next_question_id(document)
        # A test with variants: the new question goes into the one named in the link
        # (?variant=), else into the first.
        ids = test_variants.variant_ids(test)
        variant = request.GET.get("variant", "")
        variant = variant if variant in ids else (ids[0] if ids else "")
    else:
        _index, existing = _question_or_404(document, question_id)
        question_type = existing["type"]
        variant = editing.variant_of(document, question_id)
    errors: list[str] = []

    if request.method != "POST":
        form = editing.blank_form(question_type) if is_new else editing.form_from_question(existing)
        return _question_page(
            request, assessment, document, question_type, question_id, form, errors, is_new, variant
        )

    form = editing.form_from_post(request.POST, question_type)
    if request.POST.get("action") == "add_option":
        editing.pad_options(form, len(form["options"]) + 1)
        return _question_page(
            request, assessment, document, question_type, question_id, form, errors, is_new, variant
        )

    question, errors = editing.build_question(form, question_type, question_id)
    if question is None:
        editing.pad_options(form, editing.MIN_OPTION_ROWS if is_new else len(form["options"]))
        return _question_page(
            request, assessment, document, question_type, question_id, form, errors, is_new, variant
        )

    if is_new:
        editing.add_question(document, question, variant)
    else:
        editing.replace_question(document, question_id, question)
    services.save_draft(assessment, document)
    messages.success(request, _("Question saved."))
    if request.POST.get("action") == "save_add" and is_new:
        url = reverse("assessments:question_new", args=[assessment.pk, question_type])
        return redirect(f"{url}?variant={variant}" if variant else url)
    url = reverse("assessments:detail", args=[assessment.pk])
    return redirect(f"{url}#question-{question_id}")


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
    # Land on the row that moved, not at the top of a long page.
    url = reverse("assessments:detail", args=[assessment.pk])
    return redirect(f"{url}#question-{question_id}")


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


@login_required
@require_POST
def variant_add(request, pk):
    """Add a variant as a copy of the last one; the teacher then changes its questions."""
    assessment = _owned_assessment(request, pk)
    document = copy.deepcopy(assessment.document)
    new_id = editing.add_variant(document)
    url = reverse("assessments:detail", args=[assessment.pk])
    if new_id is None:
        messages.error(request, _("A variant cannot be added to this test."))
        return redirect(url)
    services.save_draft(assessment, document)
    messages.success(
        request,
        _("%(name)s added as a copy. Change its questions so that it differs.")
        % {"name": test_variants.label(document["test"], new_id)},
    )
    return redirect(f"{url}#variant-{new_id}")


@login_required
def variant_delete(request, pk, variant_id):
    assessment = _owned_assessment(request, pk)
    document = copy.deepcopy(assessment.document)
    test = document.get("test") or {}
    variant = test_variants.find(test, variant_id)
    if variant is None:
        raise Http404("No such variant")
    name = test_variants.label(test, variant_id)
    if request.method == "POST":
        editing.delete_variant(document, variant_id)
        services.save_draft(assessment, document)
        messages.success(request, _("%(name)s deleted.") % {"name": name})
        return redirect("assessments:detail", pk=assessment.pk)
    return render(
        request,
        "assessments/editor/confirm_delete_variant.html",
        {
            "assessment": assessment,
            "name": name,
            "count": len(variant.get("questions") or []),
            "last_two": len(test_variants.variant_list(test)) == 2,
        },
    )


@login_required
def delete(request, pk):
    """Delete a test. Its sessions and their results go too, so this asks first."""
    assessment = _owned_assessment(request, pk)
    if request.method == "POST":
        title = assessment.title
        services.delete_assessment(assessment)
        messages.success(request, _('Test "%(title)s" deleted.') % {"title": title})
        return redirect("assessments:list")
    return render(
        request,
        "assessments/editor/confirm_delete_test.html",
        {"assessment": assessment, "impact": services.deletion_impact(assessment)},
    )


@login_required
def preview(request, pk):
    """Show the draft as a taker would see it. Nothing is saved."""
    assessment = _owned_assessment(request, pk)
    result = import_document(assessment.document)
    back_url = reverse("assessments:detail", args=[assessment.pk])
    if not result.ok:
        messages.error(request, _("Fix the errors in the test before previewing it."))
        return redirect(back_url)
    test = result.document["test"]
    url = reverse("assessments:preview", args=[assessment.pk])
    # A test with variants: the teacher chooses which one to look at (?variant=).
    ids = test_variants.variant_ids(test)
    variant = request.GET.get("variant", "")
    variant = variant if variant in ids else (ids[0] if ids else "")
    return render_preview(
        request,
        test,
        {
            "url": f"{url}?variant={variant}" if variant else url,
            "back_url": back_url,
            "variant": variant or None,
            "variants": [
                {
                    "label": test_variants.label(test, v),
                    "url": f"{url}?variant={v}",
                    "current": v == variant,
                }
                for v in ids
            ],
        },
    )
