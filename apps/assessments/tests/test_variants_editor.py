"""Variants on the test pages and in the browser editor."""

import copy
import re

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.assessments import editing, services
from apps.exchange import variants
from apps.exchange.importer import import_document

pytestmark = pytest.mark.django_db


def choice(text):
    return {
        "type": "single_choice",
        "text": text,
        "options": [{"text": "yes", "correct": True}, {"text": "no"}],
    }


def document(*variant_texts, plain=None):
    body = {"title": "Draft", "language": "en"}
    if plain is not None:
        body["questions"] = [choice(t) for t in plain]
    else:
        body["variants"] = [{"questions": [choice(t) for t in texts]} for texts in variant_texts]
    result = import_document({"format": "knowledge-tester/test", "version": 1, "test": body})
    assert result.ok, result.report.as_text()
    return result.document


@pytest.fixture
def teacher(db):
    return get_user_model().objects.create_user("t", password="pw")


@pytest.fixture
def client_t(client, teacher):
    client.force_login(teacher)
    return client


@pytest.fixture
def make(teacher):
    def factory(doc):
        return services.create_assessment(services.ensure_default_project(teacher), doc)

    return factory


@pytest.fixture
def plain(make):
    return make(document(plain=["one", "two"]))


@pytest.fixture
def two(make):
    return make(document(["a1", "a2"], ["b1", "b2"]))


def texts(test):
    test.refresh_from_db()
    body = test.document["test"]
    if "variants" not in body:
        return [q["text"] for q in body["questions"]]
    return [[q["text"] for q in v["questions"]] for v in body["variants"]]


def choice_post(text):
    return {
        "text": text,
        "points": "1",
        "opt_text": ["yes", "no"],
        "opt_id": ["", ""],
        "opt_weight": ["", ""],
        "opt_correct": ["0"],
        "action": "save",
    }


# --- pure functions ---------------------------------------------------------------------------


def test_adding_a_variant_to_a_plain_test_copies_its_questions_with_new_ids():
    doc = document(plain=["one", "two"])
    assert editing.add_variant(doc) == "v2"
    body = doc["test"]
    assert "questions" not in body
    assert [v["id"] for v in body["variants"]] == ["v1", "v2"]
    assert [[q["text"] for q in v["questions"]] for v in body["variants"]] == [["one", "two"]] * 2
    ids = [q["id"] for q in variants.all_questions(body)]
    assert len(set(ids)) == 4
    assert import_document(doc).ok
    # a copy, not the same objects
    body["variants"][1]["questions"][0]["text"] = "changed"
    assert body["variants"][0]["questions"][0]["text"] == "one"


def test_a_third_variant_copies_the_last_one_and_the_limit_holds():
    doc = document(["a"], ["b"])
    assert editing.add_variant(doc) == "v3"
    assert [q["text"] for q in doc["test"]["variants"][2]["questions"]] == ["b"]
    while len(doc["test"]["variants"]) < variants.MAX_VARIANTS:
        assert editing.add_variant(doc)
    assert editing.add_variant(doc) is None
    assert len(doc["test"]["variants"]) == variants.MAX_VARIANTS
    assert import_document(doc).ok


def test_a_test_without_questions_gets_no_variant():
    doc = editing.blank_document("Empty", "en")
    assert editing.add_variant(doc) is None
    assert "variants" not in doc["test"]


def test_deleting_down_to_one_variant_gives_a_plain_test_again():
    doc = document(["a"], ["b"], ["c"])
    assert editing.delete_variant(doc, "v2") is True
    assert [v["id"] for v in doc["test"]["variants"]] == ["v1", "v3"]
    assert editing.delete_variant(doc, "v1") is True
    assert "variants" not in doc["test"]
    assert [q["text"] for q in doc["test"]["questions"]] == ["c"]
    assert editing.delete_variant(doc, "v3") is False  # nothing by that name any more
    assert import_document(doc).ok


def test_question_operations_stay_inside_the_variant_that_holds_the_question():
    doc = document(["a1", "a2"], ["b1", "b2"])
    second = doc["test"]["variants"][1]["questions"]
    b1, b2 = second[0]["id"], second[1]["id"]
    assert editing.variant_of(doc, b1) == "v2" and editing.find_question(doc, b2)[0] == 1
    assert editing.move_question(doc, b1, "up") is False  # already first in its variant
    assert editing.move_question(doc, b1, "down") is True
    assert [q["text"] for q in second] == ["b2", "b1"]
    new_id = editing.duplicate_question(doc, b1)
    assert [q["text"] for q in second] == ["b2", "b1", "b1"]
    assert new_id not in (b1, b2) and editing.variant_of(doc, new_id) == "v2"
    assert editing.delete_question(doc, b2) is True
    assert [q["text"] for q in doc["test"]["variants"][0]["questions"]] == ["a1", "a2"]
    assert [q["text"] for q in second] == ["b1", "b1"]
    assert import_document(doc).ok


def test_settings_can_be_saved_for_a_test_with_variants():
    doc = document(["a"], ["b"])
    form = editing.settings_form(doc["test"])
    form["title"] = "Renamed"
    form["time_limit_minutes"] = "12"
    updated, errors = editing.apply_settings(copy.deepcopy(doc["test"]), form)
    assert errors == [] and updated["title"] == "Renamed"
    assert [v["id"] for v in updated["variants"]] == ["v1", "v2"] and "questions" not in updated


# --- pages ------------------------------------------------------------------------------------


def test_test_page_lists_every_variant_with_its_own_links(client_t, two):
    html = client_t.get(reverse("assessments:detail", args=[two.pk])).content.decode()
    assert 'id="variant-v1"' in html and 'id="variant-v2"' in html
    assert "Variant 1" in html and "Variant 2" in html and "2 variants" in html
    for text in ("a1", "a2", "b1", "b2"):
        assert f">{text}</a>" in html
    new_url = reverse("assessments:question_new", args=[two.pk, "open"])
    assert f'href="{new_url}?variant=v1"' in html and f'href="{new_url}?variant=v2"' in html
    assert reverse("assessments:variant_delete", args=[two.pk, "v2"]) in html
    assert reverse("assessments:variant_add", args=[two.pk]) in html
    listing = client_t.get(reverse("assessments:list")).content.decode()
    assert "&times; 2" in listing


def test_plain_test_page_offers_to_add_a_variant_and_nothing_else_changes(client_t, plain):
    html = client_t.get(reverse("assessments:detail", args=[plain.pk])).content.decode()
    assert reverse("assessments:variant_add", args=[plain.pk]) in html
    assert "variant-head" not in html and "?variant=" not in html
    assert "2 questions" in html


def test_add_variant_button_then_edit_the_copy(client_t, plain):
    response = client_t.post(reverse("assessments:variant_add", args=[plain.pk]))
    assert response["Location"] == reverse("assessments:detail", args=[plain.pk]) + "#variant-v2"
    assert texts(plain) == [["one", "two"], ["one", "two"]]
    copied = plain.document["test"]["variants"][1]["questions"][0]["id"]
    page = client_t.get(reverse("assessments:question_edit", args=[plain.pk, copied]))
    assert "Variant 2" in page.content.decode()
    client_t.post(reverse("assessments:question_edit", args=[plain.pk, copied]), choice_post("uno"))
    assert texts(plain) == [["one", "two"], ["uno", "two"]]
    assert client_t.get(reverse("assessments:variant_add", args=[plain.pk])).status_code == 405


def test_a_new_question_goes_into_the_variant_named_in_the_link(client_t, two):
    url = reverse("assessments:question_new", args=[two.pk, "single_choice"])
    page = client_t.get(f"{url}?variant=v2").content.decode()
    assert "Variant 2" in page and "New question 3" in page
    client_t.post(f"{url}?variant=v2", choice_post("b3"))
    assert texts(two) == [["a1", "a2"], ["b1", "b2", "b3"]]
    # no variant named, or a wrong one: the first
    client_t.post(url, choice_post("a3"))
    client_t.post(f"{url}?variant=nope", choice_post("a4"))
    assert texts(two) == [["a1", "a2", "a3", "a4"], ["b1", "b2", "b3"]]
    # "save and add another" stays in the same variant
    response = client_t.post(f"{url}?variant=v2", {**choice_post("b4"), "action": "save_add"})
    assert response["Location"] == f"{url}?variant=v2"
    assert texts(two)[1] == ["b1", "b2", "b3", "b4"]
    ids = [q["id"] for q in variants.all_questions(two.document["test"])]
    assert len(ids) == len(set(ids)) == 8


def test_delete_variant_asks_first_and_explains_the_last_two(client_t, two):
    url = reverse("assessments:variant_delete", args=[two.pk, "v2"])
    page = client_t.get(url).content.decode()
    assert "Delete Variant 2?" in page and "Its 2 questions are deleted with it." in page
    assert "becomes a test without variants" in page
    assert texts(two) == [["a1", "a2"], ["b1", "b2"]]
    assert client_t.post(url)["Location"] == reverse("assessments:detail", args=[two.pk])
    assert texts(two) == ["a1", "a2"]
    assert client_t.get(url).status_code == 404
    assert (
        client_t.get(reverse("assessments:variant_delete", args=[two.pk, "zz"])).status_code == 404
    )


def _without_tokens(html: str) -> str:
    """The page carries a random attempt token (a UUID): "a1" may occur in it by chance."""
    return re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "", html)


def test_preview_shows_the_chosen_variant_and_links_to_the_others(client_t, two):
    url = reverse("assessments:preview", args=[two.pk])
    first = _without_tokens(client_t.get(url).content.decode())
    assert "a1" in first and "b1" not in first
    assert "<strong>Variant 1</strong>" in first and f'href="{url}?variant=v2"' in first
    second = _without_tokens(client_t.get(f"{url}?variant=v2").content.decode())
    assert "b1" in second and "a1" not in second and "<strong>Variant 2</strong>" in second
    assert f'action="{url}?variant=v2"' in second
    assert client_t.get(f"{url}?variant=nope").status_code == 200


def test_publishing_and_exporting_a_test_with_variants(client_t, two, teacher):
    revision, error, created = services.publish(two, teacher)
    assert error is None and created
    assert [v["id"] for v in revision.test["variants"]] == ["v1", "v2"]
    exported = client_t.get(reverse("assessments:export", args=[two.pk])).content.decode()
    again = import_document(exported)
    assert again.ok and again.document == revision.document


def test_import_page_previews_the_variants(client_t):
    import json

    raw = document(["a1", "a2"], ["b1"])
    response = client_t.post(
        reverse("assessments:import"), {"document": json.dumps(raw), "action": "check"}
    )
    html = response.content.decode()
    assert (
        "2 variants" in html
        and "Variant 1 (2 questions" in html
        and "Variant 2 (1 question" in html
    )
    assert "Every student gets one of them, in turn." in html
