"""Linking attempts to students after the fact (KT-604): matching and the page."""

from types import SimpleNamespace

import pytest
from django.test import Client
from django.urls import reverse

from apps.delivery import linking, services
from apps.delivery.models import Attempt
from apps.people.models import Group

from .conftest import make_student, pick, start

# --- the pure matching code --------------------------------------------------------------------


def stud(pk, name, group_id=None):
    return SimpleNamespace(pk=pk, full_name=name, group_id=group_id)


ROSTER = [
    stud(1, "Іваненко Петро"),
    stud(2, "Шевченко Оксана"),
    stud(3, "Дем'ян Коваль"),
    stud(4, "Мельник Олена"),
    stud(5, "Мельник Олег"),
    stud(6, "Бондаренко Марія-Софія"),
    stud(7, "Петренко Іван"),
]


def top(typed, students=ROSTER):
    found = linking.suggest(typed, students)
    return [(s.student.pk, s.kind) for s in found]


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("Іваненко Петро", [(1, "exact")]),
        ("  іваненко   ПЕТРО ", [(1, "exact")]),  # case and spacing
        ("Петро Іваненко", [(1, "words")]),  # swapped order
        ("ПЕТРО іваненко", [(1, "words")]),
        ("Дем'ян Коваль", [(3, "exact")]),
        ("Дем’ян Коваль", [(3, "exact")]),  # typographic apostrophe
        ("Демʼян Коваль", [(3, "exact")]),  # modifier-letter apostrophe
        ("Коваль Дем`ян", [(3, "words")]),  # backtick + swapped
        ("Бондаренко Марія–Софія", [(6, "exact")]),  # en dash for the hyphen
        ("Іваненко Петр", [(1, "fuzzy")]),  # typo
        ("Іваненко Петрро", [(1, "fuzzy")]),
        ("Шевченко Оксанна", [(2, "fuzzy")]),
        ("Оксана Шевченко Богданівна", [(2, "fuzzy")]),  # patronymic typed too
        ("Нікому Невідомий", []),
        ("", []),
        ("   ", []),
        ("Іван", []),  # a single word is too little to suggest anything
    ],
)
def test_suggest_table(typed, expected):
    assert top(typed) == expected


def test_similar_names_of_different_people_are_ranked_but_not_exact():
    found = top("Мельник Олен")
    assert found[0] == (4, "fuzzy")  # Олена is closest
    assert (5, "fuzzy") in found  # Олег is a plausible hint too
    assert all(kind == "fuzzy" for _pk, kind in found)


def test_ranking_exact_before_words_before_fuzzy():
    students = [stud(1, "Anna Lee"), stud(2, "Lee Anna"), stud(3, "Anna Leee")]
    found = linking.suggest("Anna Lee", students)
    assert [(s.student.pk, s.kind) for s in found] == [(1, "exact"), (2, "words"), (3, "fuzzy")]
    assert found[0].score > found[1].score > found[2].score
    assert found[0].percent == 100 and found[0].confident and not found[2].confident


def test_top_three_only():
    students = [stud(i, f"Anna Le{c}") for i, c in enumerate("aiouknm", start=1)]
    assert len(linking.suggest("Anna Lee", students)) == 3
    assert len(linking.suggest("Anna Lee", students, limit=5)) == 5


def test_threshold_is_applied():
    assert linking.suggest("Zzzz Yyyy", [stud(1, "Anna Lee")]) == []
    found = linking.suggest("Anna Lea", [stud(1, "Anna Lee")])
    assert found and found[0].score >= linking.FUZZY_THRESHOLD


def test_preselected_only_for_confident_unique_matches():
    exact = linking.suggest("Іваненко Петро", ROSTER)
    assert linking.preselected(exact).pk == 1
    words = linking.suggest("Петро Іваненко", ROSTER)
    assert linking.preselected(words).pk == 1
    assert linking.preselected(linking.suggest("Іваненко Петр", ROSTER)) is None  # fuzzy
    assert linking.preselected([]) is None


def test_preselected_with_duplicates_prefers_the_session_class():
    twins = [stud(1, "Ira Kov", group_id=10), stud(2, "Ira Kov", group_id=20)]
    found = linking.suggest("Ira Kov", twins)
    assert linking.preselected(found) is None  # ambiguous
    assert linking.preselected(found, group_id=20).pk == 2
    assert linking.preselected(found, group_id=99) is None
    both_in_class = [stud(1, "Ira Kov", group_id=10), stud(2, "Ira Kov", group_id=10)]
    assert linking.preselected(linking.suggest("Ira Kov", both_in_class), group_id=10) is None


def test_exact_beats_same_words_for_preselection():
    students = [stud(1, "Lee Anna"), stud(2, "Anna Lee")]
    assert linking.preselected(linking.suggest("Anna Lee", students)).pk == 2


# --- the page ----------------------------------------------------------------------------------


@pytest.fixture
def teacher_client(client, teacher):
    client.force_login(teacher)
    return client


@pytest.fixture
def link_url(sitting):
    return reverse("delivery:link", args=[sitting.pk])


@pytest.fixture
def people(teacher, group):
    return {
        "ivan": make_student(teacher, group, "Іван Петренко", pin="1111"),
        "olena": make_student(teacher, group, "Олена Мельник"),
        "oleg": make_student(teacher, group, "Олег Мельник"),
        "gone": make_student(teacher, group, "Іванна Пішла", is_active=False),
        "loner": make_student(teacher, None, "Без Класу"),
    }


def taker(sitting, name, **extra):
    c = Client()
    start(c, sitting, name=name)
    return sitting.attempts.order_by("-pk").first()


def option_values(html, select_name):
    import re

    block = re.search(rf'<select id="{select_name}".*?</select>', html, re.S).group(0)
    return re.findall(r'<option value="(\d*)"', block), re.findall(
        r'<option value="(\d+)" selected', block
    )


@pytest.mark.django_db
class TestLinkPage:
    def test_login_required_and_post_only_applies(self, client, sitting):
        url = reverse("delivery:link", args=[sitting.pk])
        r = client.get(url)
        assert r.status_code == 302 and "/accounts/login/" in r["Location"]
        assert client.post(url, {}).status_code == 302

    def test_lists_the_attempts_with_typed_name_status_and_score(
        self, teacher_client, sitting, people, link_url
    ):
        a = taker(sitting, "Петренко Іван")
        services.finalize(a)
        html = teacher_client.get(link_url).content.decode()
        assert "Петренко Іван" in html and "Submitted" in html and "not linked" in html
        assert f'name="student_{a.pk}"' in html
        assert "0 of 1 attempts are linked" in html

    def test_same_words_in_other_order_is_preselected(
        self, teacher_client, sitting, people, link_url
    ):
        a = taker(sitting, "Петренко Іван")
        values, selected = option_values(
            teacher_client.get(link_url).content.decode(), f"student_{a.pk}"
        )
        assert selected == [str(people["ivan"].pk)]
        assert "same words" in teacher_client.get(link_url).content.decode()

    def test_fuzzy_match_is_a_hint_not_preselected(self, teacher_client, sitting, people, link_url):
        a = taker(sitting, "Мельник Олен")
        html = teacher_client.get(link_url).content.decode()
        values, selected = option_values(html, f"student_{a.pk}")
        assert selected == []  # nothing pre-selected
        assert "Suggestions:" in html and "similar" in html
        assert str(people["olena"].pk) in values and str(people["oleg"].pk) in values

    def test_unrelated_name_has_no_suggestions(self, teacher_client, sitting, people, link_url):
        a = taker(sitting, "Хтось Інший")
        html = teacher_client.get(link_url).content.decode()
        assert option_values(html, f"student_{a.pk}")[1] == []
        assert "Suggestions:" not in html

    def test_options_are_my_active_students_session_class_first(
        self, teacher_client, teacher, other_teacher, sitting, people, link_url
    ):
        other_class = Group.objects.create(owner=teacher, name="5-Б")
        make_student(teacher, other_class, "Богдан З П'ятого")
        make_student(other_teacher, None, "Чужий Учень")
        taker(sitting, "x")
        sitting.group = people["ivan"].group
        sitting.save()
        html = teacher_client.get(link_url).content.decode()
        assert "Чужий Учень" not in html and "Іванна Пішла" not in html  # foreign, inactive
        assert (
            html.index('label="7-A"') < html.index('label="5-Б"') < html.index('label="No class"')
        )
        assert "Богдан З П&#x27;ятого" in html

    def test_apply_links_and_never_touches_the_typed_name(
        self, teacher_client, sitting, people, link_url
    ):
        a = taker(sitting, "Петренко Іван")
        b = taker(sitting, "Мельник Олен")
        r = teacher_client.post(
            link_url,
            {f"student_{a.pk}": people["ivan"].pk, f"student_{b.pk}": people["olena"].pk},
        )
        assert r.status_code == 302 and r["Location"] == link_url
        a.refresh_from_db()
        b.refresh_from_db()
        assert a.student == people["ivan"] and b.student == people["olena"]
        assert a.taker["name"] == "Петренко Іван" and b.taker["name"] == "Мельник Олен"
        page = teacher_client.get(link_url).content.decode()
        assert "2 of 2 attempts are linked" in page
        assert "Saved: 2 attempts updated." in page

    def test_unlink_and_repoint(self, teacher_client, sitting, people, link_url):
        a = taker(sitting, "Петренко Іван")
        b = taker(sitting, "Мельник Олена")
        Attempt.objects.filter(pk=a.pk).update(student=people["ivan"])
        Attempt.objects.filter(pk=b.pk).update(student=people["ivan"])
        html = teacher_client.get(link_url).content.decode()
        assert "Unlink (no student)" in html
        assert option_values(html, f"student_{a.pk}")[1] == [str(people["ivan"].pk)]
        teacher_client.post(
            link_url, {f"student_{a.pk}": "", f"student_{b.pk}": people["olena"].pk}
        )
        a.refresh_from_db()
        b.refresh_from_db()
        assert a.student is None and b.student == people["olena"]

    def test_attempts_missing_from_the_post_are_left_alone(
        self, teacher_client, sitting, people, link_url
    ):
        a = taker(sitting, "Петренко Іван")
        b = taker(sitting, "Мельник Олена")
        Attempt.objects.filter(pk=b.pk).update(student=people["olena"])
        teacher_client.post(link_url, {f"student_{a.pk}": people["ivan"].pk})
        b.refresh_from_db()
        assert b.student == people["olena"]

    def test_nothing_changed_message(self, teacher_client, sitting, people, link_url):
        a = taker(sitting, "x")
        r = teacher_client.post(link_url, {f"student_{a.pk}": ""}, follow=True)
        assert "Nothing to change." in r.content.decode()

    @pytest.mark.parametrize("who", ["foreign", "inactive", "unknown", "garbage"])
    def test_a_student_the_teacher_may_not_use_is_rejected_and_nothing_is_saved(
        self, teacher_client, other_teacher, sitting, people, link_url, who
    ):
        foreign = make_student(other_teacher, None, "Чужий Учень")
        a = taker(sitting, "Петренко Іван")
        b = taker(sitting, "Мельник Олена")
        bad = {
            "foreign": foreign.pk,
            "inactive": people["gone"].pk,
            "unknown": 99999,
            "garbage": "1 OR 1=1",
        }[who]
        r = teacher_client.post(
            link_url, {f"student_{a.pk}": people["ivan"].pk, f"student_{b.pk}": bad}
        )
        assert r.status_code == 400
        html = r.content.decode()
        assert "Nothing was saved" in html and "Чужий Учень" not in html
        a.refresh_from_db()
        b.refresh_from_db()
        assert a.student is None and b.student is None  # all or nothing

    def test_attempts_of_another_session_are_ignored(
        self, teacher_client, teacher, revision, sitting, people, link_url
    ):
        elsewhere = services.create_sitting(revision=revision, user=teacher, title="other")
        foreign_attempt = taker(elsewhere, "Петренко Іван")
        mine = taker(sitting, "Петренко Іван")
        teacher_client.post(
            link_url,
            {
                f"student_{foreign_attempt.pk}": people["ivan"].pk,
                f"student_{mine.pk}": people["ivan"].pk,
            },
        )
        foreign_attempt.refresh_from_db()
        mine.refresh_from_db()
        assert foreign_attempt.student is None and mine.student == people["ivan"]

    def test_voided_attempts_are_not_listed(self, teacher_client, sitting, people, link_url):
        a = taker(sitting, "Петренко Іван")
        Attempt.objects.filter(pk=a.pk).update(status=Attempt.Status.VOIDED)
        html = teacher_client.get(link_url).content.decode()
        assert f"student_{a.pk}" not in html
        assert "Nobody has taken this session yet" in html
        teacher_client.post(link_url, {f"student_{a.pk}": people["ivan"].pk})
        a.refresh_from_db()
        assert a.student is None

    def test_a_linked_student_who_left_the_class_is_kept_on_save(
        self, teacher_client, sitting, people, link_url
    ):
        a = taker(sitting, "Іванна Пішла")
        Attempt.objects.filter(pk=a.pk).update(student=people["gone"])
        html = teacher_client.get(link_url).content.decode()
        assert option_values(html, f"student_{a.pk}")[1] == [str(people["gone"].pk)]
        r = teacher_client.post(link_url, {f"student_{a.pk}": people["gone"].pk})
        assert r.status_code == 302
        a.refresh_from_db()
        assert a.student == people["gone"]

    def test_unlinked_attempts_come_first(self, teacher_client, sitting, people, link_url):
        a = taker(sitting, "Аня")
        b = taker(sitting, "Яна")
        Attempt.objects.filter(pk=a.pk).update(student=people["ivan"])
        html = teacher_client.get(link_url).content.decode()
        assert html.index(f"student_{b.pk}") < html.index(f"student_{a.pk}")

    def test_class_session_shows_everyone_linked(
        self, client, teacher_client, teacher, revision, group, pupils, link_url
    ):
        class_sitting = services.create_sitting(
            revision=revision, user=teacher, title="c", group=group
        )
        pick(client, class_sitting, pupils["ann"])
        url = reverse("delivery:link", args=[class_sitting.pk])
        html = teacher_client.get(url).content.decode()
        assert "1 of 1 attempts are linked" in html and "Ann Lee" in html
        attempt = class_sitting.attempts.get()
        assert option_values(html, f"student_{attempt.pk}")[1] == [str(pupils["ann"].pk)]

    def test_no_students_yet_says_so(self, teacher_client, sitting, link_url):
        taker(sitting, "Хтось")
        html = teacher_client.get(link_url).content.decode()
        assert "You have no active students yet" in html and reverse("people:groups") in html

    def test_empty_session(self, teacher_client, link_url):
        assert "Nobody has taken this session yet" in teacher_client.get(link_url).content.decode()

    def test_a_different_teacher_gets_404s(self, client, other_teacher, sitting, people):
        a = taker(sitting, "Петренко Іван")
        client.force_login(other_teacher)
        url = reverse("delivery:link", args=[sitting.pk])
        assert client.get(url).status_code == 404
        assert client.post(url, {f"student_{a.pk}": people["ivan"].pk}).status_code == 404
        a.refresh_from_db()
        assert a.student is None
        # a foreign pk reveals nothing, same as an unknown one
        assert client.get(reverse("delivery:link", args=[999999])).status_code == 404

    def test_admin_links_with_the_owners_students_only(
        self, client, admin_user, teacher, sitting, people
    ):
        mine = make_student(admin_user, None, "Админ Учень")
        a = taker(sitting, "Петренко Іван")
        client.force_login(admin_user)
        url = reverse("delivery:link", args=[sitting.pk])
        html = client.get(url).content.decode()
        assert "Іван Петренко" in html and "Админ Учень" not in html
        assert client.post(url, {f"student_{a.pk}": mine.pk}).status_code == 400
        assert client.post(url, {f"student_{a.pk}": people["ivan"].pk}).status_code == 302
        a.refresh_from_db()
        assert a.student == people["ivan"]

    def test_links_to_the_page(self, teacher_client, sitting, link_url):
        for url in (
            reverse("delivery:share", args=[sitting.pk]),
            reverse("delivery:list"),
            reverse("reports:session", args=[sitting.pk]),
        ):
            assert link_url in teacher_client.get(url).content.decode(), url

    def test_page_budget_does_not_grow_per_row(
        self, teacher_client, sitting, people, link_url, django_assert_max_num_queries
    ):
        for i in range(12):
            taker(sitting, f"Student {i}")
        with django_assert_max_num_queries(12):
            assert teacher_client.get(link_url).status_code == 200


def test_apply_links_service_is_atomic(db, teacher, sitting, group):
    s1 = make_student(teacher, group, "A One")
    pool = {s1.pk: s1}
    a = services.start_attempt(sitting, {"name": "a"})
    b = services.start_attempt(sitting, {"name": "b"})
    with pytest.raises(services.LinkError):
        services.apply_links([a, b], {a.pk: s1.pk, b.pk: 424242}, pool)
    a.refresh_from_db()
    assert a.student is None
    assert services.apply_links([a, b], {a.pk: s1.pk, b.pk: None}, pool) == 1
    assert services.apply_links([a, b], {a.pk: s1.pk}, pool) == 0  # unchanged
