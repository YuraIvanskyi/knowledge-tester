"""The browser editor: create a test, edit settings, add/edit/move/duplicate/delete questions."""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.assessments import editing, services
from apps.assessments.models import Assessment
from apps.exchange.importer import import_document

pytestmark = pytest.mark.django_db


@pytest.fixture
def teacher(db):
    return get_user_model().objects.create_user("t", password="pw")


@pytest.fixture
def other(db):
    return get_user_model().objects.create_user("o", password="pw")


@pytest.fixture
def client_t(client, teacher):
    client.force_login(teacher)
    return client


@pytest.fixture
def blank(teacher):
    project = services.ensure_default_project(teacher)
    return services.create_assessment(project, editing.blank_document("Draft", "en"))


def add(client, test, qtype, **post):
    url = reverse("assessments:question_new", args=[test.pk, qtype])
    return client.post(url, post)


def choice_post(*rows, **extra):
    """rows: (text, correct) tuples -> POST data with parallel opt_* lists."""
    data = {
        "text": "Which?",
        "points": "1",
        "opt_text": [r[0] for r in rows],
        "opt_id": [""] * len(rows),
        "opt_weight": [""] * len(rows),
        "opt_correct": [str(i) for i, r in enumerate(rows) if r[1]],
        "action": "save",
    }
    data.update(extra)
    return data


def questions(test):
    test.refresh_from_db()
    return test.document["test"]["questions"]


# --- access ---------------------------------------------------------------------------------


def test_login_required(client, blank):
    urls = [
        reverse("assessments:create"),
        reverse("assessments:settings", args=[blank.pk]),
        reverse("assessments:question_new", args=[blank.pk, "open"]),
        reverse("assessments:question_edit", args=[blank.pk, "q1"]),
        reverse("assessments:question_delete", args=[blank.pk, "q1"]),
    ]
    for url in urls:
        response = client.get(url)
        assert response.status_code == 302 and "login" in response["Location"]
    for name in ("question_move", "question_duplicate"):
        response = client.post(reverse(f"assessments:{name}", args=[blank.pk, "q1"]))
        assert response.status_code == 302 and "login" in response["Location"]


def test_other_teacher_gets_404(client, other, blank):
    client.force_login(other)
    assert client.get(reverse("assessments:settings", args=[blank.pk])).status_code == 404
    response = client.post(
        reverse("assessments:question_new", args=[blank.pk, "open"]), {"text": "x", "points": "1"}
    )
    assert response.status_code == 404
    assert questions(blank) == []


def test_unknown_type_and_question_are_404(client_t, blank):
    assert (
        client_t.get(reverse("assessments:question_new", args=[blank.pk, "essay"])).status_code
        == 404
    )
    assert (
        client_t.get(reverse("assessments:question_edit", args=[blank.pk, "q9"])).status_code == 404
    )


# --- create ---------------------------------------------------------------------------------


def test_create_blank_test(client_t, teacher):
    response = client_t.post(reverse("assessments:create"), {"title": "Fractions"})
    test = Assessment.objects.get(title="Fractions")
    assert response.status_code == 302 and response["Location"] == reverse(
        "assessments:detail", args=[test.pk]
    )
    assert test.project.owner == teacher
    assert test.document["test"]["questions"] == []
    page = client_t.get(response["Location"])
    assert page.status_code == 200
    assert "No questions yet" in page.content.decode()
    assert page.context["valid"] is False  # cannot publish an empty test


def test_create_requires_title_and_can_start_a_project(client_t, teacher):
    response = client_t.post(reverse("assessments:create"), {"title": "  "})
    assert response.status_code == 200 and not Assessment.objects.exists()
    client_t.post(reverse("assessments:create"), {"title": "T", "new_project": "Grade 7"})
    assert Assessment.objects.get().project.title == "Grade 7"


# --- adding questions -----------------------------------------------------------------------


def test_add_single_choice_and_publish(client_t, blank):
    response = add(client_t, blank, "single_choice", **choice_post(("Kyiv", True), ("Lviv", False)))
    assert response.status_code == 302
    (q,) = questions(blank)
    assert q["id"] == "q1" and q["type"] == "single_choice"
    assert [o["correct"] for o in q["options"]] == [True, False]
    assert blank.has_unpublished_changes
    assert import_document(blank.document).ok
    revision, error, created = services.publish(blank, blank.project.owner)
    assert error is None and created and revision.number == 1


def test_blank_option_rows_are_dropped(client_t, blank):
    add(client_t, blank, "multiple_choice", **choice_post(("a", True), ("", False), ("b", True)))
    (q,) = questions(blank)
    assert [o["text"] for o in q["options"]] == ["a", "b"]
    assert q["scoring"] == "partial"


def test_choice_without_correct_option_is_rejected_and_keeps_input(client_t, blank):
    response = add(
        client_t, blank, "single_choice", **choice_post(("Kyiv", False), ("Lviv", False))
    )
    assert response.status_code == 200
    assert questions(blank) == []
    assert response.context["errors"]
    html = response.content.decode()
    assert 'value="Kyiv"' in html and "Which?" in html


def test_bad_points_is_a_form_error(client_t, blank):
    response = add(client_t, blank, "open", text="Explain", points="lots")
    assert response.status_code == 200 and questions(blank) == []
    assert "Points must be a number" in response.content.decode()


def test_points_accept_decimal_comma(client_t, blank):
    add(client_t, blank, "open", text="Explain", points="1,5", rubric="Two ideas")
    (q,) = questions(blank)
    assert q["points"] == 1.5 and q["rubric"] == "Two ideas"


def test_choose_n(client_t, blank):
    add(client_t, blank, "choose_n", **choice_post(("a", True), ("b", True), ("c", False), n="2"))
    (q,) = questions(blank)
    assert q["n"] == 2
    response = add(client_t, blank, "choose_n", **choice_post(("a", True), ("b", False), n="x"))
    assert response.status_code == 200 and len(questions(blank)) == 1


def test_short_answer_numeric(client_t, blank):
    add(
        client_t,
        blank,
        "short_answer",
        text="3/4 as decimal?",
        points="1",
        accept="0.75\n\n 0,75 ",
        mode="numeric",
        tolerance="0.01",
    )
    (q,) = questions(blank)
    assert q["mode"] == "numeric" and q["accept"] == ["0.75", "0,75"] and q["tolerance"] == 0.01
    assert q["case_sensitive"] is False


def test_short_answer_needs_accepted_answers(client_t, blank):
    response = add(client_t, blank, "short_answer", text="Q", points="1", mode="text")
    assert response.status_code == 200 and questions(blank) == []


def test_add_option_action_only_adds_a_row(client_t, blank):
    response = add(
        client_t,
        blank,
        "single_choice",
        **choice_post(("a", True), ("b", False), action="add_option"),
    )
    assert response.status_code == 200 and questions(blank) == []
    assert len(response.context["form"]["options"]) == 3


def test_save_and_add_another_returns_to_new_form(client_t, blank):
    response = add(client_t, blank, "open", text="Explain", points="2", action="save_add")
    assert response["Location"] == reverse("assessments:question_new", args=[blank.pk, "open"])
    add(client_t, blank, "open", text="Again", points="2")
    assert [q["id"] for q in questions(blank)] == ["q1", "q2"]


# --- editing --------------------------------------------------------------------------------


def test_edit_keeps_ids_and_weights(client_t, blank):
    add(client_t, blank, "multiple_choice", **choice_post(("a", True), ("b", False)))
    (q,) = questions(blank)
    url = reverse("assessments:question_edit", args=[blank.pk, "q1"])
    page = client_t.get(url)
    assert page.status_code == 200 and "Edit question" in page.content.decode()
    ids = [o["id"] for o in q["options"]]
    response = client_t.post(
        url,
        {
            "text": "Changed",
            "points": "3",
            "scoring": "all_or_nothing",
            "opt_text": ["a", "b", "c"],
            "opt_id": [*ids, ""],
            "opt_weight": ["", "", ""],
            "opt_correct": ["0", "2"],
            "action": "save",
        },
    )
    assert response.status_code == 302
    (q,) = questions(blank)
    assert q["id"] == "q1" and q["text"] == "Changed" and q["points"] == 3
    assert q["scoring"] == "all_or_nothing"
    assert [o["id"] for o in q["options"]][:2] == ids
    assert [o["correct"] for o in q["options"]] == [True, False, True]


def test_editing_a_published_test_marks_unpublished_changes(client_t, blank, teacher):
    add(client_t, blank, "open", text="Explain", points="1")
    blank.refresh_from_db()
    assert services.publish(blank, teacher)[1] is None
    blank.refresh_from_db()
    assert not blank.has_unpublished_changes
    client_t.post(
        reverse("assessments:question_edit", args=[blank.pk, "q1"]),
        {"text": "Explain more", "points": "1"},
    )
    blank.refresh_from_db()
    assert blank.has_unpublished_changes and blank.status == "published"
    assert blank.revisions.get().document["test"]["questions"][0]["text"] == "Explain"


# --- move / duplicate / delete --------------------------------------------------------------


@pytest.fixture
def three(client_t, blank):
    for text in ("one", "two", "three"):
        add(client_t, blank, "open", text=text, points="1")
    return blank


def texts(test):
    return [q["text"] for q in questions(test)]


def test_move_up_and_down(client_t, three):
    move = lambda qid, d: client_t.post(  # noqa: E731
        reverse("assessments:question_move", args=[three.pk, qid]), {"direction": d}
    )
    move("q3", "up")
    assert texts(three) == ["one", "three", "two"]
    move("q1", "down")
    assert texts(three) == ["three", "one", "two"]
    move("q3", "up")  # already first: no change
    assert texts(three) == ["three", "one", "two"]
    assert move("q1", "sideways").status_code == 302


def test_duplicate_inserts_copy_after_original_with_new_id(client_t, three):
    client_t.post(reverse("assessments:question_duplicate", args=[three.pk, "q1"]))
    qs = questions(three)
    assert [q["text"] for q in qs] == ["one", "one", "two", "three"]
    assert len({q["id"] for q in qs}) == 4


def test_delete_asks_first_then_deletes(client_t, three):
    url = reverse("assessments:question_delete", args=[three.pk, "q2"])
    assert client_t.get(url).status_code == 200
    assert len(questions(three)) == 3
    client_t.post(url)
    assert texts(three) == ["one", "three"]
    assert editing.next_question_id(three.document) == "q4"


def test_detail_lists_actions_for_each_question(client_t, three):
    html = client_t.get(reverse("assessments:detail", args=[three.pk])).content.decode()
    assert reverse("assessments:question_edit", args=[three.pk, "q2"]) in html
    assert reverse("assessments:question_new", args=[three.pk, "short_answer"]) in html
    assert reverse("assessments:settings", args=[three.pk]) in html


# --- settings -------------------------------------------------------------------------------


def settings_post(**overrides):
    data = {
        "title": "Renamed",
        "description": "About",
        "language": "uk",
        "time_limit_minutes": "20",
        "max_attempts": "2",
        "shuffle_options": "on",
        "show_result": "full",
        "grading_enabled": "on",
        "scale": "ua_12",
        "pass_percent": "60",
        "tf_key": ["name", "", ""],
        "tf_label": ["Full name", "Class", ""],
        "tf_required": ["0"],
        "action": "save",
    }
    data.update(overrides)
    return data


def test_settings_save(client_t, three):
    url = reverse("assessments:settings", args=[three.pk])
    assert client_t.get(url).status_code == 200
    response = client_t.post(url, settings_post())
    assert response.status_code == 302
    three.refresh_from_db()
    test = three.document["test"]
    assert three.title == "Renamed" and three.language == "uk"
    assert test["settings"] == {
        "time_limit_minutes": 20,
        "shuffle_questions": False,
        "shuffle_options": True,
        "one_question_per_page": False,
        "show_result": "full",
        "max_attempts": 2,
    }
    assert test["taker_fields"] == [
        {"key": "name", "label": "Full name", "required": True},
        {"key": "class", "label": "Class", "required": False},
    ]
    assert test["grading"] == {"enabled": True, "scale": "ua_12", "pass_percent": 60}
    assert len(test["questions"]) == 3
    assert import_document(three.document).ok


def test_settings_errors_do_not_save(client_t, three):
    url = reverse("assessments:settings", args=[three.pk])
    response = client_t.post(url, settings_post(time_limit_minutes="soon", title="Nope"))
    assert response.status_code == 200 and response.context["errors"]
    three.refresh_from_db()
    assert three.title == "Draft"
    response = client_t.post(url, settings_post(title=""))
    assert response.status_code == 200 and three.title == "Draft"


def test_settings_empty_time_limit_means_none_and_add_field(client_t, three):
    url = reverse("assessments:settings", args=[three.pk])
    client_t.post(url, settings_post(time_limit_minutes=""))
    three.refresh_from_db()
    assert three.document["test"]["settings"]["time_limit_minutes"] is None
    response = client_t.post(url, settings_post(action="add_field"))
    assert response.status_code == 200
    assert len(response.context["form"]["taker_fields"]) == 4


def test_settings_form_defaults_for_a_new_test(client_t, blank):
    response = client_t.get(reverse("assessments:settings", args=[blank.pk]))
    form = response.context["form"]
    assert form["max_attempts"] == "1" and form["scale"] == "percent"
    assert form["taker_fields"][0]["label"] == "Full name"


# --- pure helpers ---------------------------------------------------------------------------


def test_field_keys_are_unique_slugs():
    form = editing.settings_form({"title": "T", "questions": []})
    form["taker_fields"] = [
        {"key": "", "label": "Class", "required": False},
        {"key": "", "label": "Class", "required": False},
    ]
    test, errors = editing.apply_settings({"title": "T"}, form)
    assert not errors
    assert [f["key"] for f in test["taker_fields"]] == ["class", "class_2"]


def test_editor_pages_are_in_ukrainian_by_default(client_t, blank, settings):
    settings.LANGUAGE_CODE = "uk"
    for url in (
        reverse("assessments:settings", args=[blank.pk]),
        reverse("assessments:question_new", args=[blank.pk, "multiple_choice"]),
        reverse("assessments:create"),
    ):
        html = client_t.get(url).content.decode()
        assert "Save " not in html and "Cancel" not in html, url
    assert (
        "Налаштування тесту"
        in client_t.get(reverse("assessments:settings", args=[blank.pk])).content.decode()
    )
