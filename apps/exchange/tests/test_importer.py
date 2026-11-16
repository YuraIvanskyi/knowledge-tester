import copy
import json
from pathlib import Path

import pytest

from apps.exchange.importer import import_document
from apps.exchange.serializer import content_hash, export_document

EXAMPLES = Path(__file__).resolve().parents[3] / "docs" / "examples"
EXAMPLE_FILES = sorted(EXAMPLES.glob("*.json"))


def doc(*questions, **test):
    return {
        "format": "knowledge-tester/test",
        "version": 1,
        "test": {"title": "T", "questions": list(questions), **test},
    }


def single(**extra):
    q = {
        "type": "single_choice",
        "text": "Q?",
        "options": [{"text": "A", "correct": True}, {"text": "B"}],
    }
    q.update(extra)
    return q


def errors_of(data):
    result = import_document(data)
    assert not result.ok
    assert result.document is None
    return [f"{i.path}: {i.message}" for i in result.report.errors]


def test_examples_exist():
    names = {p.stem for p in EXAMPLE_FILES}
    assert {"full", "minimal", "single_choice", "multiple_choice", "choose_n"} <= names
    assert {"short_answer", "open"} <= names


@pytest.mark.parametrize("path", EXAMPLE_FILES, ids=lambda p: p.stem)
def test_examples_import_cleanly(path):
    result = import_document(path.read_bytes())
    assert result.ok, result.report.as_text()
    assert result.report.warnings == []


def test_full_example_keeps_content():
    result = import_document((EXAMPLES / "full.json").read_text(encoding="utf-8"))
    test = result.document["test"]
    assert [q["id"] for q in test["questions"]] == ["q1", "q2", "q3", "q4", "q5"]
    assert test["grading"]["scale"] == "ua_12"
    assert test["settings"]["time_limit_minutes"] == 15
    assert test["questions"][3]["accept"] == ["0.75"]


def test_minimal_gets_ids_and_defaults():
    result = import_document((EXAMPLES / "minimal.json").read_text(encoding="utf-8"))
    test = result.document["test"]
    assert result.document["format"] == "knowledge-tester/test"
    q = test["questions"][0]
    assert q["id"] == "q1"
    assert [o["id"] for o in q["options"]] == ["a", "b"]
    assert q["points"] == 1 and q["required"] is False and q["penalty"] == 0
    assert test["settings"]["show_result"] == "score"
    assert test["settings"]["max_attempts"] == 1
    assert test["settings"]["time_limit_minutes"] is None
    assert test["taker_fields"] == [{"key": "name", "label": "Full name", "required": True}]
    assert test["grading"]["scale"] == "percent"
    assert test["language"] == "en"


def test_generated_ids_skip_explicit_ones():
    result = import_document(
        doc(
            single(id="q1"),
            single(),
            single(options=[{"id": "a", "text": "x", "correct": True}, {"text": "y"}]),
        )
    )
    qs = result.document["test"]["questions"]
    assert [q["id"] for q in qs] == ["q1", "q2", "q3"]
    assert [o["id"] for o in qs[2]["options"]] == ["a", "b"]


def test_accepts_dict_bytes_and_bom():
    data = doc(single())
    assert import_document(data).ok
    raw = json.dumps(data).encode("utf-8")
    assert import_document(raw).ok
    assert import_document(b"\xef\xbb\xbf" + raw).ok


def test_markdown_fence_is_stripped_with_warning():
    text = "```json\n" + json.dumps(doc(single())) + "\n```"
    result = import_document(text)
    assert result.ok
    assert "code fence" in result.report.warnings[0].message


def test_bad_json_reports_line_and_column():
    result = import_document('{\n  "format": "knowledge-tester/test",\n  "version": 1,\n')
    assert not result.ok
    message = result.report.errors[0].message
    assert "line 4" in message and "column" in message


def test_empty_and_non_object():
    assert "empty" in errors_of("   ")[0]
    assert "top level" in errors_of("[1, 2]")[0]


def test_missing_format_and_version_have_fix_hints():
    errs = errors_of({"test": {"title": "T", "questions": [single()]}})
    assert any(e.startswith("format:") and '"knowledge-tester/test"' in e for e in errs)
    assert any(e.startswith("version:") and '"version": 1' in e for e in errs)


def test_unsupported_version():
    data = doc(single())
    data["version"] = 2
    assert "unsupported version 2" in errors_of(data)[0]


def test_single_choice_needs_exactly_one_correct():
    none = single(options=[{"text": "A"}, {"text": "B"}])
    two = single(options=[{"text": "A", "correct": True}, {"text": "B", "correct": True}])
    errs = errors_of(doc(none, two))
    assert 'test.questions[0] (id "q1", single_choice): no option is marked correct' in errs[0]
    assert "2 options are marked correct" in errs[1]


def test_multiple_choice_needs_a_correct_option():
    q = {"type": "multiple_choice", "text": "Q", "options": [{"text": "A"}, {"text": "B"}]}
    errs = errors_of(doc(q))
    assert errs == [
        'test.questions[0] (id "q1", multiple_choice): no option is marked correct. '
        'Add "correct": true to at least one option.'
    ]


def test_choose_n_must_match_correct_count():
    options = [{"text": "A", "correct": True}, {"text": "B"}, {"text": "C"}]
    q = {"type": "choose_n", "text": "Q", "n": 2, "options": options}
    assert '"n" is 2 but 1 option(s)' in errors_of(doc(q))[0]
    q_missing = {"type": "choose_n", "text": "Q", "options": options}
    assert '"n" is missing' in errors_of(doc(q_missing))[0]


def test_per_option_requires_weights():
    q = {
        "type": "multiple_choice",
        "text": "Q",
        "scoring": "per_option",
        "options": [{"text": "A", "correct": True, "weight": 1}, {"text": "B"}],
    }
    assert 'have no "weight": "b"' in errors_of(doc(q))[0]


def test_duplicate_ids():
    errs = errors_of(doc(single(id="x"), single(id="x")))
    assert 'id "x" is already used by test.questions[0]' in errs[0]
    dup_opts = single(options=[{"id": "a", "text": "A", "correct": True}, {"id": "a", "text": "B"}])
    assert 'option id "a" is used more than once' in errors_of(doc(dup_opts))[0]


def test_option_count_limits():
    one = single(options=[{"text": "A", "correct": True}])
    assert "needs 2 to 20 options, found 1" in errors_of(doc(one))[0]
    no_options = {"type": "single_choice", "text": "Q"}
    assert "found 0" in errors_of(doc(no_options))[0]


def test_short_answer_checks():
    assert "no accepted answers" in errors_of(doc({"type": "short_answer", "text": "Q"}))[0]
    numeric = {"type": "short_answer", "text": "Q", "mode": "numeric", "accept": ["abc"]}
    assert "is not a number" in errors_of(doc(numeric))[0]
    ok = {"type": "short_answer", "text": "Q", "mode": "numeric", "accept": ["0,75", 2, 1.5]}
    result = import_document(doc(ok))
    assert result.ok
    assert result.document["test"]["questions"][0]["accept"] == ["0,75", "2", "1.5"]


def test_custom_scale_checks():
    base = {"scale": "custom"}
    assert "no thresholds" in errors_of(doc(single(), grading=base))[0]
    unsorted = {
        **base,
        "thresholds": [{"min_percent": 0, "label": "F"}, {"min_percent": 50, "label": "P"}],
    }
    assert "sorted from the highest" in errors_of(doc(single(), grading=unsorted))[0]
    dup = {
        **base,
        "thresholds": [{"min_percent": 50, "label": "P"}, {"min_percent": 0, "label": "P"}],
    }
    assert "every" in errors_of(doc(single(), grading=dup))[0]
    good = {
        **base,
        "thresholds": [{"min_percent": 50, "label": "P"}, {"min_percent": 0, "label": "F"}],
    }
    result = import_document(doc(single(), grading=good))
    assert result.ok
    assert result.document["test"]["grading"]["thresholds"][0] == {"min_percent": 50, "label": "P"}


def test_duplicate_taker_field_keys():
    fields = [{"key": "name", "label": "A"}, {"key": "name", "label": "B"}]
    assert "used more than once" in errors_of(doc(single(), taker_fields=fields))[0]


def test_structural_errors_are_plain_and_path_based():
    errs = errors_of(doc(single(points=-1), single(type="single_chioce")))
    assert "test.questions[0].points: must be 0 or more, got -1." in errs
    assert any("test.questions[1].type" in e and 'Did you mean "single_choice"?' in e for e in errs)
    errs = errors_of(doc(single(points=0.3)))
    assert "multiple of 0.5" in errs[0]
    errs = errors_of({"format": "knowledge-tester/test", "version": 1, "test": {"questions": []}})
    assert any(e.startswith("test.title: required") for e in errs)
    assert any(e.startswith("test.questions: must have at least 1") for e in errs)


def test_wrong_value_types():
    errs = errors_of(doc(single(), settings={"max_attempts": "lots", "show_result": "all"}))
    assert any("test.settings.max_attempts: must be a whole number" in e for e in errs)
    assert any(
        'test.settings.show_result: must be one of: "none", "score", "full"' in e for e in errs
    )


def test_unknown_fields_warn_with_hint():
    result = import_document(doc(single(colour="red"), settings={"shuffle": True}))
    assert result.ok
    warns = {i.path: i.message for i in result.report.warnings}
    assert (
        warns["test.settings.shuffle"] == 'unknown field, ignored. Did you mean "shuffle_options"?'
    )
    assert "test.questions[0].colour" in warns
    assert "colour" not in result.document["test"]["questions"][0]


def test_field_not_used_by_type_warns():
    q = {"type": "open", "text": "Q", "options": [{"text": "A"}], "rubric": "r"}
    result = import_document(doc(q))
    assert result.ok
    assert result.report.warnings[0].path == "test.questions[0].options"
    assert "not used by open" in result.report.warnings[0].message
    assert "options" not in result.document["test"]["questions"][0]


def test_report_as_text():
    result = import_document(
        doc(single(options=[{"text": "A"}, {"text": "B"}]), settings={"shuffle": 1})
    )
    text = result.report.as_text()
    assert "ERROR  test.questions[0]" in text
    assert "WARN   test.settings.shuffle" in text
    assert import_document(doc(single())).report.as_text() == "No problems found."


@pytest.mark.parametrize("path", EXAMPLE_FILES, ids=lambda p: p.stem)
def test_round_trip_is_identical(path):
    first = import_document(path.read_bytes()).document
    exported = export_document(first)
    second = import_document(exported).document
    assert second == first
    assert export_document(second) == exported
    assert content_hash(first) == content_hash(second)


def test_export_rejects_invalid_document():
    bad = copy.deepcopy(import_document(doc(single())).document)
    bad["test"]["questions"][0]["options"][0]["correct"] = False
    with pytest.raises(ValueError):
        export_document(bad)


def test_importing_a_normalised_document_changes_nothing():
    normalised = import_document((EXAMPLES / "full.json").read_bytes()).document
    again = import_document(copy.deepcopy(normalised))
    assert again.document == normalised
    assert again.report.warnings == []


# --- hostile numbers and types: an error in the report, never an exception ----------------------


@pytest.mark.parametrize("points", [float("inf"), float("-inf"), float("nan"), 1e308, 1e9])
def test_absurd_points_are_reported_not_raised(points):
    result = import_document(doc(single(points=points)))
    assert not result.ok
    assert any("points" in issue.path for issue in result.report.errors)


@pytest.mark.parametrize("text", ['{"weight": NaN}', '{"weight": Infinity}'])
def test_option_weight_must_be_a_real_number(text):
    weight = json.loads(text)["weight"]
    q = {
        "type": "multiple_choice",
        "text": "Q?",
        "scoring": "per_option",
        "options": [{"text": "A", "correct": True, "weight": weight}, {"text": "B"}],
    }
    assert not import_document(doc(q)).ok


def test_tolerance_must_be_finite():
    q = {"type": "short_answer", "text": "Q?", "mode": "number", "accept": ["1"]}
    q["tolerance"] = float("inf")
    assert not import_document(doc(q)).ok


@pytest.mark.parametrize("bad_type", [["single_choice"], {"a": 1}, 7, None])
def test_a_question_type_that_is_not_a_string_is_an_error(bad_type):
    q = single()
    q["type"] = bad_type
    result = import_document(doc(q))
    assert not result.ok
    assert any("type" in issue.path for issue in result.report.errors)


def test_the_json_text_form_of_infinity_is_also_handled():
    text = json.dumps(doc(single())).replace('"text": "Q?"', '"text": "Q?", "points": Infinity')
    assert not import_document(text).ok


def test_the_textbook_prompt_shows_a_file_that_imports_cleanly():
    """docs/llm/test-from-textbook.uk.prompt.md teaches a chat AI by example: the example must
    be a valid file with every question type, or every generated test inherits the mistake."""
    import re
    from pathlib import Path

    prompt = Path(__file__).resolve().parents[3] / "docs/llm/test-from-textbook.uk.prompt.md"
    blocks = re.findall(r"```json\n(.*?)\n```", prompt.read_text(encoding="utf-8"), re.S)
    assert len(blocks) == 2  # the full example, then the short one with variants
    with_variants = import_document(blocks[1])
    assert with_variants.ok and not with_variants.report.warnings
    assert [v["title"] for v in with_variants.document["test"]["variants"]] == [
        "Варіант 1",
        "Варіант 2",
    ]
    result = import_document(blocks[0])
    assert result.ok and not result.report.warnings, result.report.as_text()
    test = result.document["test"]
    assert {q["type"] for q in test["questions"]} == {
        "single_choice",
        "multiple_choice",
        "choose_n",
        "short_answer",
        "open",
    }
    assert test["language"] == "uk" and test["grading"]["scale"] == "ua_12"
