import json
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.assessments.models import Assessment

EXAMPLES = Path(__file__).resolve().parents[3] / "docs" / "examples"


@pytest.mark.django_db
def test_import_test_command(tmp_path):
    get_user_model().objects.create_user("ann", password="x")
    call_command("import_test", str(EXAMPLES / "full.json"), project="Math", user="ann")
    a = Assessment.objects.get()
    assert a.project.title == "Math" and a.project.owner.username == "ann"
    assert a.title == "Fractions: basics"
    assert a.document["test"]["questions"][0]["id"] == "q1"


@pytest.mark.django_db
def test_import_test_command_rejects_invalid(tmp_path):
    get_user_model().objects.create_user("ann", password="x")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(CommandError):
        call_command("import_test", str(bad), project="Math", user="ann")
    assert Assessment.objects.count() == 0


def test_export_schema_command(settings, tmp_path):
    settings.BASE_DIR = tmp_path
    call_command("export_schema")
    schema = json.loads((tmp_path / "schema" / "test.v1.schema.json").read_text(encoding="utf-8"))
    assert schema["$schema"].endswith("2020-12/schema")
    assert "format" in schema["properties"]


def test_import_test_survives_two_projects_with_the_same_title(tmp_path, django_user_model):
    from django.core.management import call_command

    from apps.assessments.models import Assessment, Project

    owner = django_user_model.objects.create_user("t", password="pw")
    Project.objects.create(owner=owner, title="Same")
    Project.objects.create(owner=owner, title="Same")  # the web form allows this
    path = tmp_path / "test.json"
    path.write_text(
        '{"format": "knowledge-tester/test", "version": 1, "test": {"title": "X", "questions": '
        '[{"type": "open", "text": "Q?"}]}}',
        encoding="utf-8",
    )
    call_command("import_test", str(path), "--user", "t", "--project", "Same")
    assert Assessment.objects.count() == 1
