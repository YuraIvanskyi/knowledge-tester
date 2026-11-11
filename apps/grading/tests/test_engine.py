from decimal import Decimal as D

import pytest

from apps.grading.engine import grade_answer, grade_test


def opts(correct: str, wrong: str, **weights):
    out = [{"id": c, "text": c.upper(), "correct": True} for c in correct]
    out += [{"id": w, "text": w.upper()} for w in wrong]
    for o in out:
        if o["id"] in weights:
            o["weight"] = weights[o["id"]]
    return out


def single(points=1, penalty=None):
    q = {"id": "s", "type": "single_choice", "points": points, "options": opts("a", "bc")}
    if penalty is not None:
        q["penalty"] = penalty
    return q


def multi(scoring=None, points=2, correct="ab", wrong="cd", **weights):
    q = {
        "id": "m",
        "type": "multiple_choice",
        "points": points,
        "options": opts(correct, wrong, **weights),
    }
    if scoring:
        q["scoring"] = scoring
    return q


def choose_n(points=2, n=2):
    return {"id": "n", "type": "choose_n", "points": points, "n": n, "options": opts("ab", "cde")}


def short(**extra):
    return {"id": "t", "type": "short_answer", "points": 1, "accept": ["Kyiv"], **extra}


def numeric(accept=("0.75",), tolerance=0, **extra):
    return short(mode="numeric", accept=list(accept), tolerance=tolerance, **extra)


OPEN = {"id": "o", "type": "open", "points": 3, "rubric": "x"}


def points(question, value):
    return grade_answer(question, value).points


# ---- single_choice ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "value", "expected", "status"),
    [
        (single(), ["a"], D("1.00"), "graded"),
        (single(), ["b"], D("0.00"), "graded"),
        (single(), ["a", "b"], D("0.00"), "graded"),
        (single(), [], D("0.00"), "unanswered"),
        (single(), None, D("0.00"), "unanswered"),
        (single(), ["zzz"], D("0.00"), "unanswered"),  # unknown option ids are ignored
        (single(), "a", D("1.00"), "graded"),  # tolerate a bare id
        (single(points=2.5), ["a"], D("2.50"), "graded"),
        # penalty applies to wrong answers only, never to blank ones
        (single(points=2, penalty=0.5), ["a"], D("2.00"), "graded"),
        (single(points=2, penalty=0.5), ["b"], D("-1.00"), "graded"),
        (single(points=2, penalty=0.5), [], D("0.00"), "unanswered"),
        (single(points=1, penalty=0.25), ["c"], D("-0.25"), "graded"),
        (single(points=1, penalty=5), ["c"], D("-1.00"), "graded"),  # clamped to 0..1
    ],
)
def test_single_choice(question, value, expected, status):
    result = grade_answer(question, value)
    assert (result.points, result.status) == (expected, status)
    assert result.max_points == D(str(question["points"])).quantize(D("0.01"))


# ---- multiple_choice --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("selected", "expected"),
    [  # worked example in plan §9.2: P = 2, C = {a, b}, I = {c, d}
        (["a", "b"], D("2.00")),
        (["a"], D("1.00")),
        (["a", "b", "c"], D("1.00")),
        (["a", "c"], D("0.00")),
        (["a", "b", "c", "d"], D("0.00")),
        (["c"], D("0.00")),  # never negative
        (["c", "d"], D("0.00")),
        (["b"], D("1.00")),
    ],
)
def test_multiple_choice_partial_worked_example(selected, expected):
    assert points(multi(), selected) == expected
    assert points(multi("partial"), selected) == expected


def test_multiple_choice_partial_rounding():
    # P = 1, |C| = 3: one correct pick = 1/3
    q = multi(points=1, correct="abc", wrong="d")
    assert points(q, ["a"]) == D("0.33")
    assert points(q, ["a", "b"]) == D("0.67")
    # 2/3 - 1/1 < 0 -> clamped to 0
    assert points(q, ["a", "b", "d"]) == D("0.00")


def test_multiple_choice_all_options_correct_has_no_wrong_term():
    q = multi(points=2, correct="abc", wrong="")
    assert points(q, ["a"]) == D("0.67")
    assert points(q, ["a", "b", "c"]) == D("2.00")


@pytest.mark.parametrize(
    ("selected", "expected"),
    [
        (["a", "b"], D("2.00")),
        (["a"], D("0.00")),
        (["a", "b", "c"], D("0.00")),
        (["c"], D("0.00")),
        ([], D("0.00")),
    ],
)
def test_multiple_choice_all_or_nothing(selected, expected):
    assert points(multi("all_or_nothing"), selected) == expected


@pytest.mark.parametrize(
    ("selected", "expected"),
    [
        (["a"], D("1.50")),
        (["a", "b"], D("2.00")),  # 1.5 + 1 = 2.5, clamped to P
        (["a", "c"], D("0.50")),  # 1.5 - 1 = 0.5
        (["c"], D("0.00")),  # -1 clamped to 0
        (["b", "d"], D("1.00")),
        (["d"], D("0.00")),
    ],
)
def test_multiple_choice_per_option(selected, expected):
    q = multi("per_option", a=1.5, b=1, c=-1, d=0)
    assert points(q, selected) == expected


def test_multiple_choice_blank_is_unanswered():
    assert grade_answer(multi(), []).status == "unanswered"


# ---- choose_n ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("selected", "expected"),
    [
        (["a", "b"], D("2.00")),
        (["a"], D("1.00")),
        (["a", "c"], D("1.00")),  # a wrong pick costs a correct slot
        (["c", "d"], D("0.00")),
        (["c"], D("0.00")),
    ],
)
def test_choose_n(selected, expected):
    assert points(choose_n(), selected) == expected


def test_choose_n_three_of_seven():
    q = {"id": "n", "type": "choose_n", "points": 3, "n": 3, "options": opts("abc", "defg")}
    assert points(q, ["a", "b", "c"]) == D("3.00")
    assert points(q, ["a", "b", "d"]) == D("2.00")
    assert points(q, ["a", "d", "e"]) == D("1.00")


# ---- short_answer text ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "value", "expected", "status"),
    [
        (short(), "Kyiv", D("1.00"), "graded"),
        (short(), "  kyiv. ", D("1.00"), "graded"),
        (short(), "KYIV", D("1.00"), "graded"),
        (short(), "Lviv", D("0.00"), "graded"),
        (short(), "", D("0.00"), "unanswered"),
        (short(), "   ", D("0.00"), "unanswered"),
        (short(), None, D("0.00"), "unanswered"),
        (short(case_sensitive=True), "kyiv", D("0.00"), "graded"),
        (short(case_sensitive=True), "Kyiv", D("1.00"), "graded"),
        (short(accept=["Kyiv", "Kiev"]), "kiev", D("1.00"), "graded"),
        # Ukrainian apostrophes
        (short(accept=["м'ята"]), "м’ята", D("1.00"), "graded"),
        (short(accept=["мʼята"]), "М'ЯТА", D("1.00"), "graded"),
        (short(accept=["м'ята"]), "м`ята", D("1.00"), "graded"),
        (short(accept=["м'ята"]), "мята", D("0.00"), "graded"),
        # dashes
        (short(accept=["Івано-Франківськ"]), "Івано–Франківськ", D("1.00"), "graded"),
        # look-alike flag
        (short(accept=["київ"]), "kиїв", D("0.00"), "graded"),
        (short(accept=["київ"], lookalike=True), "kиїв", D("1.00"), "graded"),
        # review_unmatched: a miss goes to review instead of 0, a hit still scores
        (short(review_unmatched=True), "Kyev", D("0.00"), "needs_review"),
        (short(review_unmatched=True), "Kyiv", D("1.00"), "graded"),
        (short(review_unmatched=True), "", D("0.00"), "unanswered"),
    ],
)
def test_short_answer_text(question, value, expected, status):
    result = grade_answer(question, value)
    assert (result.points, result.status) == (expected, status)


# ---- short_answer numeric ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "value", "expected"),
    [
        (numeric(), "0.75", D("1.00")),
        (numeric(), "0,75", D("1.00")),
        (numeric(), " 0,750 ", D("1.00")),
        (numeric(), ".75", D("1.00")),
        (numeric(), "0.76", D("0.00")),
        (numeric(), "abc", D("0.00")),
        (numeric(), "3/4", D("0.00")),
        (numeric(accept=("0,75",)), "0.75", D("1.00")),  # accepted value with comma
        (numeric(accept=(0.75,)), "0.75", D("1.00")),  # JSON number
        (numeric(accept=(2,)), "2,0", D("1.00")),
        (numeric(tolerance=0.01), "0,76", D("1.00")),
        (numeric(tolerance=0.01), "0,74", D("1.00")),
        (numeric(tolerance=0.01), "0,77", D("0.00")),
        (numeric(tolerance="0,05"), "0.8", D("1.00")),
        (numeric(accept=("1", "10"), tolerance=0.5), "9,6", D("1.00")),
        (numeric(accept=("1", "10"), tolerance=0.5), "5", D("0.00")),
        (numeric(accept=("-2.5",), tolerance=0.1), "−2,45", D("1.00")),
    ],
)
def test_short_answer_numeric(question, value, expected):
    assert points(question, value) == expected


def test_numeric_blank_and_review_unmatched():
    assert grade_answer(numeric(), "").status == "unanswered"
    assert grade_answer(numeric(review_unmatched=True), "abc").status == "needs_review"
    assert grade_answer(numeric(review_unmatched=True), "0,75").status == "graded"


# ---- open, ungraded, errors -------------------------------------------------------------


def test_open_needs_review():
    result = grade_answer(OPEN, "An essay")
    assert (result.points, result.max_points, result.status) == (
        D("0.00"),
        D("3.00"),
        "needs_review",
    )
    assert grade_answer(OPEN, "  ").status == "unanswered"
    assert grade_answer(OPEN, None).status == "unanswered"


def test_zero_points_is_ungraded():
    q = {**single(), "points": 0}
    assert grade_answer(q, ["a"]).max_points == D("0")
    assert grade_answer(q, ["a"]).points == D("0")
    assert grade_answer(q, ["a"]).status == "graded"
    assert grade_answer({**OPEN, "points": 0}, "text").status == "graded"  # nothing to review
    assert grade_answer(q, []).status == "unanswered"


def test_default_points_is_one():
    q = single()
    del q["points"]
    assert grade_answer(q, ["a"]).points == D("1.00")


def test_unknown_type_raises():
    with pytest.raises(ValueError):
        grade_answer({"id": "x", "type": "matching", "points": 1}, "x")


# ---- grade_test -------------------------------------------------------------------------


def make_test(**grading):
    return {
        "title": "T",
        "grading": {"enabled": True, **grading},
        "questions": [single(1) | {"id": "q1"}, multi() | {"id": "q2"}, OPEN | {"id": "q3"}],
    }


def test_grade_test_totals_and_provisional():
    test = make_test(scale="points")
    result = grade_test(test, {"q1": ["a"], "q2": ["a"], "q3": "essay"})
    assert result.score == D("2.00")
    assert result.max_score == D("6.00")
    assert result.percent == D("33.3")
    assert result.grade == "2 / 6"
    assert result.pending_reviews == 1
    assert result.provisional is True
    assert set(result.per_question) == {"q1", "q2", "q3"}
    assert result.per_question["q3"].status == "needs_review"


def test_grade_test_manual_score_wins_and_clears_pending():
    test = make_test()
    answers = {"q1": ["a"], "q2": ["a", "b"], "q3": "essay"}
    result = grade_test(test, answers, {"q3": D("2.5")})
    assert result.score == D("5.50")
    assert result.percent == D("91.7")
    assert result.pending_reviews == 0
    assert result.provisional is False
    assert result.per_question["q3"].status == "graded"
    # manual overrides an auto-graded answer too, and is clamped to 0..max
    result = grade_test(test, answers, {"q1": D("0"), "q3": D("9")})
    assert result.per_question["q1"].points == D("0.00")
    assert result.per_question["q3"].points == D("3.00")


def test_grade_test_blank_everything_is_zero():
    result = grade_test(make_test(), {})
    assert (result.score, result.max_score, result.percent) == (D("0.00"), D("6.00"), D("0.0"))
    assert result.pending_reviews == 0  # blank open answers need no review
    assert all(r.status == "unanswered" for r in result.per_question.values())


def test_grade_test_total_never_below_zero_with_penalty():
    test = {
        "grading": {"enabled": True},
        "questions": [
            single(1, penalty=1) | {"id": "q1"},
            single(1, penalty=1) | {"id": "q2"},
        ],
    }
    result = grade_test(test, {"q1": ["b"], "q2": ["c"]})
    assert result.per_question["q1"].points == D("-1.00")
    assert result.score == D("0.00")
    assert result.percent == D("0.0")
    # a negative question still reduces the other questions' gains
    result = grade_test(test, {"q1": ["a"], "q2": ["c"]})
    assert result.score == D("0.00")


def test_grade_test_ungraded_questions_excluded_from_max():
    test = {
        "grading": {"enabled": True},
        "questions": [single(1) | {"id": "q1"}, single(0) | {"id": "q2"}],
    }
    result = grade_test(test, {"q1": ["a"], "q2": ["a"]})
    assert (result.score, result.max_score, result.percent) == (D("1.00"), D("1.00"), D("100.0"))


def test_grade_test_only_ungraded_questions():
    test = {"grading": {"enabled": True}, "questions": [single(0) | {"id": "q1"}]}
    result = grade_test(test, {"q1": ["a"]})
    assert result.max_score == D("0.00")
    assert result.percent is None
    assert result.grade == ""


def test_grade_test_grading_disabled_scores_nothing():
    test = make_test()
    test["grading"]["enabled"] = False
    result = grade_test(test, {"q1": ["a"], "q2": ["a"], "q3": "essay"}, {"q3": D("3")})
    assert result.score is None
    assert result.max_score is None
    assert result.percent is None
    assert result.grade == ""
    assert result.pending_reviews == 0
    assert result.provisional is False
    assert result.per_question["q1"].status == "graded"
    assert result.per_question["q1"].points == D("0")


def test_grade_test_missing_grading_block_defaults_to_enabled_percent():
    test = {"questions": [single(1) | {"id": "q1"}, single(2) | {"id": "q2"}]}
    result = grade_test(test, {"q1": ["a"], "q2": ["a"]})
    assert result.score == D("3.00")
    assert result.grade == "100.0 %"


def test_percent_rounds_half_up_to_one_place():
    test = {
        "grading": {"enabled": True},
        "questions": [single(1) | {"id": f"q{i}"} for i in range(1, 9)],
    }
    # 1/8 = 12.5 %; 5/8 = 62.5 %
    assert grade_test(test, {"q1": ["a"]}).percent == D("12.5")
    six_questions = {
        "grading": {"enabled": True},
        "questions": [single(1) | {"id": f"q{i}"} for i in range(1, 7)],
    }
    assert grade_test(six_questions, {"q1": ["a"]}).percent == D("16.7")


def test_grade_test_ua_12_scale():
    test = make_test(scale="ua_12")
    result = grade_test(test, {"q1": ["a"], "q2": ["a", "b"], "q3": "x"}, {"q3": D("3")})
    assert result.percent == D("100.0")
    assert result.grade == "12"
