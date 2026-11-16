"""Taking a test that has variants: who gets which, and that everything after it (the page,
autosave, submit, grading, the teacher's live table) works on the taker's own variant."""

import json
import re
from collections import Counter
from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse

from apps.delivery import services
from apps.delivery.models import Answer, Attempt
from apps.exchange import variants
from apps.exchange.importer import import_document

from .conftest import make_revision, start

pytestmark = pytest.mark.django_db


def choice(text, right, wrong, points=1):
    return {
        "type": "single_choice",
        "text": text,
        "points": points,
        "options": [{"text": right, "correct": True}, {"text": wrong}],
    }


def variant_document(count=2, **settings):
    """`count` variants. Variant n asks "V<n> first" and "V<n> second" (2 points); variant 1 also
    has a third question, so the variants differ in length and in total points."""
    body = []
    for n in range(1, count + 1):
        questions = [
            choice(f"V{n} first", f"right-{n}a", f"wrong-{n}a"),
            choice(f"V{n} second", f"right-{n}b", f"wrong-{n}b", points=2),
        ]
        if n == 1:
            questions.append(
                {"type": "short_answer", "text": "V1 third", "accept": ["yes"], "points": 1}
            )
        body.append({"questions": questions})
    raw = {
        "format": "knowledge-tester/test",
        "version": 1,
        "test": {"title": "Parallel", "settings": settings, "variants": body},
    }
    result = import_document(raw)
    assert result.ok, result.report.as_text()
    return result.document


@pytest.fixture
def make_variant_sitting(teacher):
    def factory(count=2, access_code="", **settings):
        revision = make_revision(teacher, variant_document(count, **settings))
        return services.create_sitting(
            revision=revision, user=teacher, title="7-A", access_code=access_code
        )

    return factory


@pytest.fixture
def sitting2(make_variant_sitting):
    return make_variant_sitting(2)


def page(sitting, client=None):
    client = client or Client()
    html = client.get(f"/s/{sitting.code}/").content.decode()
    token = re.search(r'name="attempt_token" value="([^"]+)"', html).group(1)
    shown = re.search(r'class="variant-tag">([^<]+)<', html).group(1)
    return client, html, token, shown


def save(client, sitting, token, answers, name="Ann"):
    return client.post(
        f"/s/{sitting.code}/save/",
        json.dumps(
            {"answers": answers, "unstarted": True, "attempt_token": token, "tf_name": name}
        ),
        content_type="application/json",
    )


# --- who gets which ----------------------------------------------------------------------------


def test_the_page_shows_one_variant_and_the_attempt_gets_exactly_that_one(sitting2):
    client, html, token, shown = page(sitting2)
    number = shown[-1]
    other = "2" if number == "1" else "1"
    assert f"V{number} first" in html and f"V{number} second" in html
    assert f"V{other} first" not in html
    assert shown == f"Variant {number}"

    assert save(client, sitting2, token, {}).status_code == 200
    attempt = sitting2.attempts.get()
    assert attempt.variant == f"v{number}" and attempt.variant_label == shown
    test = sitting2.revision.test
    own_ids = [q["id"] for q in variants.view(test, attempt.variant)["questions"]]
    assert sorted(attempt.question_order) == sorted(own_ids)
    # the page the student comes back to is still the same variant
    again = client.get(f"/s/{sitting2.code}/take/").content.decode()
    assert f"V{number} first" in again and f"V{other} first" not in again
    assert f'class="variant-tag">{shown}<' in again


@pytest.mark.parametrize("count", [2, 3])
def test_pages_are_handed_out_in_turn_so_the_class_is_split_evenly(make_variant_sitting, count):
    sitting = make_variant_sitting(count)
    shown = [page(sitting)[3] for _n in range(count * 6)]
    assert Counter(shown) == {f"Variant {n}": 6 for n in range(1, count + 1)}
    # in turn: any `count` students in a row have `count` different variants
    for index in range(len(shown) - count + 1):
        assert len(set(shown[index : index + count])) == count


def test_two_sessions_take_turns_independently(make_variant_sitting):
    first, second = make_variant_sitting(2), make_variant_sitting(2)
    for sitting in (first, second, first, second):
        page(sitting)
    assert Counter(page(first)[3] for _n in range(4)) == {"Variant 1": 2, "Variant 2": 2}


def test_without_a_cache_the_variant_is_still_assigned(sitting2, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("cache is down")

    monkeypatch.setattr(services.cache, "add", broken)
    assert page(sitting2)[3] in ("Variant 1", "Variant 2")


def test_the_start_form_of_an_access_code_session_assigns_variants_in_turn(make_variant_sitting):
    sitting = make_variant_sitting(2, access_code="OPEN")
    for name in ("Ann", "Bob", "Cy", "Di"):
        start(Client(), sitting, name, access_code="OPEN")
    assert Counter(a.variant for a in sitting.attempts.all()) == {"v1": 2, "v2": 2}
    for attempt in sitting.attempts.all():
        own = {q["id"] for q in attempt.test["questions"]}
        assert set(attempt.question_order) == own


def test_a_token_of_the_page_keeps_its_variant_through_a_failed_start(sitting2):
    client, _html, token, shown = page(sitting2)
    # submit without a name: the page comes back with the same token and the same variant
    response = client.post(
        f"/s/{sitting2.code}/submit/",
        {"unstarted": "1", "attempt_token": token, "form_sent": "1", "tf_name": ""},
    )
    html = response.content.decode()
    assert f'value="{token}"' in html and f'class="variant-tag">{shown}<' in html
    assert sitting2.attempts.count() == 0


def test_a_plain_test_has_no_variant_anywhere(sitting):
    client = Client()
    html = client.get(f"/s/{sitting.code}/").content.decode()
    assert "variant-tag" not in html
    start(Client(), sitting, "Ann")
    attempt = sitting.attempts.get()
    assert attempt.variant == "" and attempt.variant_label == ""
    assert attempt.test is sitting.revision.test


# --- answering and grading ---------------------------------------------------------------------


def start_in(sitting, variant_id, name):
    """Open pages until one shows the wanted variant, then start an attempt on it."""
    for _try in range(10):
        client, _html, token, _shown = page(sitting)
        if variants.for_token(sitting.revision.test, token) == variant_id:
            assert save(client, sitting, token, {}, name=name).json()["started"] is True
            return client, sitting.attempts.get(token=token)
    raise AssertionError("variant never came up")


def right_answers(attempt):
    answers = {}
    for question in attempt.test["questions"]:
        if question["type"] == "single_choice":
            answers[question["id"]] = [o["id"] for o in question["options"] if o.get("correct")]
        else:
            answers[question["id"]] = question["accept"][0]
    return answers


def test_each_variant_is_graded_against_its_own_questions_and_total(sitting2):
    client1, first = start_in(sitting2, "v1", "Ann")
    client2, second = start_in(sitting2, "v2", "Bob")
    for client, attempt in ((client1, first), (client2, second)):
        data = {"attempt_token": str(attempt.token), "form_sent": "1"}
        for qid, value in right_answers(attempt).items():
            data[f"q_{qid}"] = value
        response = client.post(f"/s/{sitting2.code}/submit/", data)
        assert response["Location"] == f"/s/{sitting2.code}/done/"
    first.refresh_from_db()
    second.refresh_from_db()
    assert (first.score, first.max_score) == (Decimal("4.00"), Decimal("4.00"))  # 3 questions
    assert (second.score, second.max_score) == (Decimal("3.00"), Decimal("3.00"))  # 2 questions
    assert first.percent == second.percent == Decimal("100.0")
    assert first.answers.count() == 3 and second.answers.count() == 2
    done = client2.get(f"/s/{sitting2.code}/done/").content.decode()
    assert 'class="variant-tag">Variant 2<' in done and "3 / 3" in done


def test_answers_for_another_variants_questions_are_not_stored(sitting2):
    client, attempt = start_in(sitting2, "v2", "Bob")
    foreign = [q["id"] for q in variants.view(sitting2.revision.test, "v1")["questions"]]
    own = attempt.test["questions"][0]
    response = client.post(
        f"/s/{sitting2.code}/save/",
        json.dumps({"answers": {foreign[0]: ["a"], foreign[2]: "yes", own["id"]: ["a"]}}),
        content_type="application/json",
    )
    assert response.json()["answered"] == 1
    assert list(attempt.answers.values_list("question_key", flat=True)) == [own["id"]]
    # a crafted submit cannot add them either
    client.post(
        f"/s/{sitting2.code}/submit/",
        {
            "attempt_token": str(attempt.token),
            "form_sent": "1",
            "confirm_unanswered": "1",
            f"q_{foreign[0]}": "a",
        },
    )
    attempt.refresh_from_db()
    assert attempt.status == Attempt.Status.SUBMITTED
    assert set(attempt.answers.values_list("question_key", flat=True)) == {
        q["id"] for q in attempt.test["questions"]
    }
    assert Answer.objects.filter(attempt=attempt, question_key__in=foreign).count() == 0


def test_unanswered_questions_are_counted_within_the_own_variant(sitting2):
    client, attempt = start_in(sitting2, "v2", "Bob")
    response = client.post(
        f"/s/{sitting2.code}/submit/", {"attempt_token": str(attempt.token), "form_sent": "1"}
    )
    html = response.content.decode()
    assert "You have answered 0 of 2 questions." in html


def test_closing_the_session_grades_every_variant(sitting2):
    start_in(sitting2, "v1", "Ann")
    start_in(sitting2, "v2", "Bob")
    assert services.close_sitting(sitting2) == 2
    totals = {a.variant: a.max_score for a in sitting2.attempts.all()}
    assert totals == {"v1": Decimal("4.00"), "v2": Decimal("3.00")}


# --- teacher pages -----------------------------------------------------------------------------


def test_live_table_shows_the_variant_and_the_takers_own_total(client, teacher, sitting2):
    start_in(sitting2, "v1", "Ann")
    start_in(sitting2, "v2", "Bob")
    stats = services.session_stats(sitting2)
    rows = {t["name"]: (t["variant"], t["total"]) for t in stats["takers"]}
    assert rows == {"Ann": ("Variant 1", 3), "Bob": ("Variant 2", 2)}
    client.force_login(teacher)
    html = client.get(reverse("delivery:share", args=[sitting2.pk])).content.decode()
    assert "Variant 1" in html and "Variant 2" in html
    assert "0 of 3" in html and "0 of 2" in html
    assert client.get(reverse("delivery:stats", args=[sitting2.pk])).json()["takers"][0]["total"]


def test_live_table_of_a_plain_test_is_unchanged(sitting):
    start(Client(), sitting, "Ann")
    taker = services.session_stats(sitting)["takers"][0]
    assert taker["variant"] == "" and taker["total"] == 5


def test_opening_a_session_says_how_many_variants_there_are(client, teacher, sitting2, sitting):
    client.force_login(teacher)
    html = client.get(reverse("delivery:create", args=[sitting2.revision_id])).content.decode()
    assert "2 variants, given to students in turn" in html and "3 questions" in html
    plain = client.get(reverse("delivery:create", args=[sitting.revision_id])).content.decode()
    assert "variant" not in plain
    assert "2 variants" in client.get(reverse("delivery:pick")).content.decode()
