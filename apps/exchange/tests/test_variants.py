"""Variants in the exchange format: the importer, the canonical document and the helpers."""

import copy
import json
from collections import Counter
from pathlib import Path

from apps.exchange import variants
from apps.exchange.document import TestDocument
from apps.exchange.importer import import_document
from apps.exchange.serializer import export_document


def single(text="Q?", **extra):
    question = {
        "type": "single_choice",
        "text": text,
        "options": [{"text": "A", "correct": True}, {"text": "B"}],
    }
    question.update(extra)
    return question


def doc(*variant_questions, **test):
    """A document with one variant per argument (each a list of questions)."""
    body = {
        "title": "T",
        "variants": [{"questions": list(questions)} for questions in variant_questions],
    }
    body.update(test)
    return {"format": "knowledge-tester/test", "version": 1, "test": body}


def errors(result):
    return [f"{i.path}: {i.message}" for i in result.report.errors]


def warnings(result):
    return [f"{i.path}: {i.message}" for i in result.report.warnings]


# --- importer -------------------------------------------------------------------------------


def test_variants_are_imported_with_ids_unique_in_the_whole_test():
    result = import_document(doc([single("a1"), single("a2")], [single("b1"), single("b2")]))
    assert result.ok and not result.report.warnings
    test = result.document["test"]
    assert "questions" not in test
    assert [v["id"] for v in test["variants"]] == ["v1", "v2"]
    assert [v["title"] for v in test["variants"]] == ["", ""]
    ids = [q["id"] for v in test["variants"] for q in v["questions"]]
    assert ids == ["q1", "q2", "q3", "q4"]
    assert [q["text"] for q in test["variants"][1]["questions"]] == ["b1", "b2"]
    # options get their letters per question, as always
    assert [o["id"] for o in test["variants"][1]["questions"][0]["options"]] == ["a", "b"]


def test_given_ids_and_titles_are_kept_and_generated_ones_avoid_them():
    document = doc([single(id="q2")], [single()], [single()])
    document["test"]["variants"][0].update(id="A", title="Row by the window")
    document["test"]["variants"][2]["id"] = "v1"
    result = import_document(document)
    assert result.ok
    got = result.document["test"]["variants"]
    assert [v["id"] for v in got] == ["A", "v2", "v1"]
    assert got[0]["title"] == "Row by the window"
    assert [q["id"] for v in got for q in v["questions"]] == ["q2", "q1", "q3"]


def test_the_same_question_id_in_two_variants_is_an_error_that_names_both_places():
    result = import_document(doc([single(id="x")], [single(id="x")]))
    assert not result.ok
    assert errors(result) == [
        'test.variants[1].questions[0]: id "x" is already used by test.variants[0].questions[0]. '
        'Ids must be unique: change this "id" or remove it to get one generated.'
    ]


def test_duplicate_variant_ids_are_an_error():
    document = doc([single()], [single()])
    for variant in document["test"]["variants"]:
        variant["id"] = "same"
    result = import_document(document)
    assert not result.ok
    assert (
        "test.variants[1]" in errors(result)[0]
        and "Variant ids must be unique" in errors(result)[0]
    )


def test_questions_and_variants_together_are_refused():
    document = doc([single()], [single()])
    document["test"]["questions"] = [single()]
    result = import_document(document)
    assert not result.ok
    assert errors(result)[0].startswith(
        'test.variants: a test has either "questions" or "variants"'
    )


def test_neither_questions_nor_variants_reads_like_the_old_missing_field():
    result = import_document(
        {"format": "knowledge-tester/test", "version": 1, "test": {"title": "T"}}
    )
    assert errors(result) == ['test.questions: required field "questions" is missing.']


def test_one_variant_becomes_a_plain_test_with_a_warning():
    result = import_document(doc([single("only")]))
    assert result.ok
    assert warnings(result) == [
        "test.variants: only one variant, so the test is imported without variants."
    ]
    test = result.document["test"]
    assert "variants" not in test and [q["text"] for q in test["questions"]] == ["only"]


def test_mistakes_inside_a_variant_are_reported_with_their_path():
    broken = single()
    broken["options"][0].pop("correct")
    result = import_document(doc([single()], [single(), broken]))
    assert not result.ok
    assert errors(result)[0].startswith(
        'test.variants[1].questions[1] (id "q3", single_choice): no option is marked correct.'
    )

    result = import_document(doc([single()], []))
    assert not result.ok
    assert errors(result) == ["test.variants[1].questions: must have at least 1 item(s), got 0."]

    too_many = import_document(doc(*[[single()] for _n in range(11)]))
    assert errors(too_many) == ["test.variants: must have at most 10 item(s), got 11."]


def test_unknown_fields_in_a_variant_and_its_questions_are_warned_about():
    document = doc([single(hnt="typo")], [single()])
    document["test"]["variants"][1]["name"] = "B"
    result = import_document(document)
    assert result.ok
    assert warnings(result) == [
        "test.variants[1].name: unknown field, ignored.",
        'test.variants[0].questions[0].hnt: unknown field, ignored. Did you mean "hint"?',
    ]


def test_unequal_point_totals_are_a_warning_not_an_error():
    result = import_document(doc([single(points=2), single()], [single(), single()]))
    assert result.ok
    assert warnings(result) == [
        "test.variants: the variants are worth different numbers of points (v1: 3, v2: 2). "
        "Grades are based on percent, so this works, but equal totals are easier to explain."
    ]


def test_export_and_import_again_give_the_same_document():
    first = import_document(doc([single("a")], [single("b")], settings={"time_limit_minutes": 5}))
    text = export_document(first.document)
    second = import_document(text)
    assert second.ok and not second.report.warnings
    assert second.document == first.document
    assert '"variants"' in text and '"questions"' in text


def test_the_published_schema_knows_variants():
    schema = TestDocument.model_json_schema()
    assert "Variant" in schema["$defs"] and "variants" in schema["$defs"]["TestBody"]["properties"]
    committed = Path(__file__).resolve().parents[3] / "schema" / "test.v1.schema.json"
    stored = json.loads(committed.read_text(encoding="utf-8"))
    assert stored["$defs"] == schema["$defs"], "run: manage.py export_schema"


def test_the_variants_example_file_imports_cleanly():
    example = Path(__file__).resolve().parents[3] / "docs" / "examples" / "variants.json"
    result = import_document(example.read_bytes())
    assert result.ok and not result.report.warnings, result.report.as_text()
    assert len(result.document["test"]["variants"]) == 2


# --- helpers --------------------------------------------------------------------------------


def stored(*variant_questions):
    return import_document(doc(*variant_questions)).document["test"]


def test_a_plain_test_has_no_variants_and_is_its_own_view():
    plain = import_document(
        {
            "format": "knowledge-tester/test",
            "version": 1,
            "test": {"title": "T", "questions": [single()]},
        }
    ).document["test"]
    assert not variants.has_variants(plain) and variants.variant_ids(plain) == []
    assert variants.view(plain, "") is plain and variants.view(plain, "v9") is plain
    assert variants.for_token(plain, "any") == "" and variants.label(plain, "") == ""
    assert variants.question_count(plain) == 1 and len(variants.all_questions(plain)) == 1


def test_view_is_the_test_with_the_questions_of_one_variant():
    test = stored([single("a1"), single("a2")], [single("b1")])
    before = copy.deepcopy(test)
    second = variants.view(test, "v2")
    assert [q["text"] for q in second["questions"]] == ["b1"]
    assert (
        "variants" not in second and second["title"] == "T" and second["grading"] == test["grading"]
    )
    assert test == before  # the stored test is not changed by looking at it
    # an id that does not exist (or none): the first variant, never an empty test
    assert [q["text"] for q in variants.view(test, "nope")["questions"]] == ["a1", "a2"]
    assert variants.question_count(test) == 2
    assert [q["text"] for q in variants.all_questions(test)] == ["a1", "a2", "b1"]


def test_labels_use_the_title_or_count_the_variants():
    document = doc([single()], [single()])
    document["test"]["variants"][1]["title"] = "Група Б"
    test = import_document(document).document["test"]
    assert variants.label(test, "v1") == "Variant 1"
    assert variants.label(test, "v2") == "Група Б"
    assert variants.label(test, "missing") == ""


def test_the_token_decides_the_variant_always_the_same_way_and_reaches_every_variant():
    test = stored([single()], [single()], [single()])
    tokens = [f"token-{n}" for n in range(300)]
    first = [variants.for_token(test, t) for t in tokens]
    assert first == [variants.for_token(test, t) for t in tokens]
    counts = Counter(first)
    assert set(counts) == {"v1", "v2", "v3"}
    assert min(counts.values()) > 60  # roughly even: 100 each on average
