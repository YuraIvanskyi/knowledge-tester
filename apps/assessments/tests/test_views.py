import json
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.assessments import services
from apps.assessments.models import Assessment, Project, Revision
from apps.exchange.importer import import_document

EXAMPLES = Path(__file__).resolve().parents[3] / "docs" / "examples"
FULL = (EXAMPLES / "full.json").read_text(encoding="utf-8")

pytestmark = pytest.mark.django_db


@pytest.fixture
def make_user():
    def make(name, **kwargs):
        return get_user_model().objects.create_user(name, password="pw", **kwargs)

    return make


@pytest.fixture
def teacher_a(make_user):
    return make_user("a")


@pytest.fixture
def teacher_b(make_user):
    return make_user("b")


@pytest.fixture
def client_a(client, teacher_a):
    client.force_login(teacher_a)
    return client


@pytest.fixture
def test_a(teacher_a):
    project = services.ensure_default_project(teacher_a)
    return services.create_assessment(project, import_document(FULL).document)


def test_login_required(client):
    for name, args in [("list", []), ("import", []), ("detail", [1]), ("export", [1])]:
        response = client.get(reverse(f"assessments:{name}", args=args))
        assert response.status_code == 302 and "login" in response["Location"]
    assert client.post(reverse("assessments:publish", args=[1])).status_code == 302


def test_list_creates_default_project(client_a, teacher_a, test_a):
    response = client_a.get(reverse("assessments:list"))
    assert response.status_code == 200
    assert Project.objects.filter(owner=teacher_a).count() == 1
    assert "My tests" in response.content.decode()
    assert "Fractions: basics" in response.content.decode()


def test_list_shows_only_own_tests(client, teacher_b, test_a):
    client.force_login(teacher_b)
    content = client.get(reverse("assessments:list")).content.decode()
    assert "Fractions: basics" not in content


def test_other_teacher_gets_404(client, teacher_b, test_a):
    client.force_login(teacher_b)
    for name in ("detail", "export"):
        assert client.get(reverse(f"assessments:{name}", args=[test_a.pk])).status_code == 404
    assert client.post(reverse("assessments:publish", args=[test_a.pk])).status_code == 404
    assert Revision.objects.count() == 0


def test_admin_sees_everything(client, make_user, test_a):
    admin = make_user("boss", role="admin")
    client.force_login(admin)
    assert client.get(reverse("assessments:detail", args=[test_a.pk])).status_code == 200
    assert "Fractions: basics" in client.get(reverse("assessments:list")).content.decode()


def test_import_check_shows_errors_and_llm_text(client_a):
    bad = json.dumps(
        {
            "format": "knowledge-tester/test",
            "version": 1,
            "test": {
                "title": "T",
                "settings": {"shuffle": True},
                "questions": [
                    {
                        "type": "multiple_choice",
                        "text": "Q",
                        "options": [{"text": "A"}, {"text": "B"}],
                    }
                ],
            },
        }
    )
    response = client_a.post(reverse("assessments:import"), {"document": bad, "action": "check"})
    content = response.content.decode()
    assert response.status_code == 200
    assert "no option is marked correct" in content
    assert "shuffle_options" in content
    assert 'id="id_report_text"' in content
    assert "Create test" not in content
    assert Assessment.objects.count() == 0


def test_import_bad_json_shows_message(client_a):
    response = client_a.post(reverse("assessments:import"), {"document": "{oops"})
    assert "not valid JSON" in response.content.decode()


def test_import_flow_check_then_create(client_a, teacher_a):
    url = reverse("assessments:import")
    response = client_a.post(url, {"document": FULL, "action": "check"})
    content = response.content.decode()
    assert "Valid." in content and "Create test" in content and "Fractions: basics" in content
    assert Assessment.objects.count() == 0

    project = services.ensure_default_project(teacher_a)
    response = client_a.post(url, {"document": FULL, "action": "create", "project": project.pk})
    assessment = Assessment.objects.get()
    assert response.status_code == 302
    assert response["Location"] == reverse("assessments:detail", args=[assessment.pk])
    assert assessment.project == project
    assert assessment.status == "draft" and assessment.has_unpublished_changes
    assert assessment.document["test"]["questions"][0]["id"] == "q1"


def test_import_create_in_new_project_and_ignores_foreign_project(client_a, teacher_a, teacher_b):
    foreign = services.ensure_default_project(teacher_b)
    client_a.post(
        reverse("assessments:import"),
        {"document": FULL, "action": "create", "project": foreign.pk},
    )
    assert Assessment.objects.get().project.owner == teacher_a
    client_a.post(
        reverse("assessments:import"),
        {"document": FULL, "action": "create", "new_project": "Algebra"},
    )
    assert Project.objects.filter(owner=teacher_a, title="Algebra").exists()


def test_import_file_upload(client_a):
    upload = SimpleUploadedFile("t.json", (EXAMPLES / "minimal.json").read_bytes())
    response = client_a.post(reverse("assessments:import"), {"file": upload, "action": "check"})
    assert "Valid." in response.content.decode()
    assert "Capitals" in response.content.decode()


def test_load_sample_fills_textarea(client_a):
    response = client_a.post(reverse("assessments:import"), {"action": "sample"})
    content = response.content.decode()
    assert "knowledge-tester/test" in content
    assert "Fractions: basics" in content


def test_import_empty_input(client_a):
    response = client_a.post(reverse("assessments:import"), {"document": "  "})
    assert "Paste the test JSON" in response.content.decode()


def test_detail_shows_questions(client_a, test_a):
    content = client_a.get(reverse("assessments:detail", args=[test_a.pk])).content.decode()
    assert "Which fraction equals 0.5?" in content
    assert "Single choice" in content
    assert "Publish" in content


def test_publish_creates_revision_once(client_a, test_a):
    url = reverse("assessments:publish", args=[test_a.pk])
    assert client_a.get(url).status_code == 405

    client_a.post(url)
    test_a.refresh_from_db()
    revision = Revision.objects.get()
    assert revision.number == 1
    assert revision.document == test_a.document
    assert len(revision.content_hash) == 64
    assert revision.test["title"] == "Fractions: basics"
    assert test_a.status == "published" and not test_a.has_unpublished_changes

    client_a.post(url)
    assert Revision.objects.count() == 1


def test_publish_after_change_creates_revision_2(client_a, test_a):
    url = reverse("assessments:publish", args=[test_a.pk])
    client_a.post(url)
    test_a.document["test"]["title"] = "Fractions: basics v2"
    test_a.has_unpublished_changes = True
    test_a.save()
    client_a.post(url)
    assert list(Revision.objects.order_by("number").values_list("number", flat=True)) == [1, 2]


def test_publish_invalid_document_is_refused(client_a, test_a):
    test_a.document["test"]["questions"][0]["options"][0]["correct"] = False
    test_a.save()
    response = client_a.post(reverse("assessments:publish", args=[test_a.pk]), follow=True)
    assert Revision.objects.count() == 0
    assert "cannot be published" in response.content.decode()


def test_detail_lists_revisions_with_open_session_link(client_a, test_a):
    client_a.post(reverse("assessments:publish", args=[test_a.pk]))
    revision = Revision.objects.get()
    try:
        link = reverse("delivery:create", args=[revision.pk])
    except Exception:
        pytest.skip("delivery:create not wired yet")
    content = client_a.get(reverse("assessments:detail", args=[test_a.pk])).content.decode()
    assert link in content


def test_export_download(client_a, test_a):
    response = client_a.get(reverse("assessments:export", args=[test_a.pk]))
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    assert "fractions-basics.json" in response["Content-Disposition"]
    assert json.loads(response.content) == test_a.document
    assert import_document(response.content).document == test_a.document


def test_seed_demo_is_idempotent():
    call_command("seed_demo")
    call_command("seed_demo")
    teacher = get_user_model().objects.get(username="teacher")
    assert teacher.check_password("teacher")
    assert get_user_model().objects.get(username="admin").is_superuser
    # the English example plus the four Ukrainian ones (see test_demo_content.py)
    assert Assessment.objects.filter(project__owner=teacher).count() == 5
    assert Revision.objects.count() == 5


# UX-06 / UX-08: one primary button per state, "Open session" where the test is, compact rows


def _primary_buttons(html):
    import re

    return re.findall(r'class="btn btn-primary"[^>]*>([^<]*)<', html)


def _detail_html(client, test):
    return client.get(reverse("assessments:detail", args=[test.pk])).content.decode()


def test_detail_never_published_has_publish_as_only_primary(client_a, test_a):
    html = _detail_html(client_a, test_a)
    assert _primary_buttons(html) == ["Publish"]
    assert "Published, version" not in html
    assert "Open session" not in html


def test_detail_published_unchanged_primary_is_open_session(client_a, test_a):
    client_a.post(reverse("assessments:publish", args=[test_a.pk]))
    revision = Revision.objects.get()
    html = _detail_html(client_a, test_a)
    assert _primary_buttons(html) == ["Open session"]
    assert reverse("delivery:create", args=[revision.pk]) in html
    assert "Published, version 1" in html
    assert "Publish changes" not in html
    assert reverse("assessments:publish", args=[test_a.pk]) not in html


def test_detail_published_with_changes_has_publish_changes_and_secondary_session(client_a, test_a):
    client_a.post(reverse("assessments:publish", args=[test_a.pk]))
    test_a.has_unpublished_changes = True
    test_a.save()
    revision = Revision.objects.get()
    html = _detail_html(client_a, test_a)
    assert _primary_buttons(html) == ["Publish changes"]
    assert "Open session (version 1)" in html
    assert f'class="btn" href="{reverse("delivery:create", args=[revision.pk])}"' in html


def test_editing_a_published_question_moves_the_test_to_changed_state(client_a, test_a):
    client_a.post(reverse("assessments:publish", args=[test_a.pk]))
    url = reverse("assessments:question_duplicate", args=[test_a.pk, "q1"])
    assert client_a.post(url).status_code == 302
    assert _primary_buttons(_detail_html(client_a, test_a)) == ["Publish changes"]


def test_question_rows_use_more_menu_and_no_edit_button(client_a, test_a):
    html = _detail_html(client_a, test_a)
    assert '<details class="more">' in html
    assert 'aria-label="Move question 2 up"' in html
    assert 'aria-label="Delete question 1"' in html
    assert (
        'class="btn btn-danger" href="'
        + reverse("assessments:question_delete", args=[test_a.pk, "q1"])
        not in html
    )
    edit = reverse("assessments:question_edit", args=[test_a.pk, "q1"])
    assert f'class="btn" href="{edit}"' not in html
    assert 'id="question-q1"' in html


def test_move_redirects_to_the_moved_row(client_a, test_a):
    url = reverse("assessments:question_move", args=[test_a.pk, "q2"])
    response = client_a.post(url, {"direction": "up"})
    assert response["Location"] == reverse("assessments:detail", args=[test_a.pk]) + "#question-q2"


def test_list_links_open_session_to_latest_revision_only_when_published(client_a, test_a):
    html = client_a.get(reverse("assessments:list")).content.decode()
    assert "Open session" not in html
    client_a.post(reverse("assessments:publish", args=[test_a.pk]))
    test_a.document["test"]["title"] = "Fractions v2"
    test_a.has_unpublished_changes = True
    test_a.save()
    client_a.post(reverse("assessments:publish", args=[test_a.pk]))
    latest = Revision.objects.get(number=2)
    old = Revision.objects.get(number=1)
    html = client_a.get(reverse("assessments:list")).content.decode()
    assert reverse("delivery:create", args=[latest.pk]) in html
    assert reverse("delivery:create", args=[old.pk]) not in html


def test_list_query_count_does_not_grow_with_tests(client_a, teacher_a, test_a):
    project = services.ensure_default_project(teacher_a)
    url = reverse("assessments:list")
    client_a.get(url)  # warm up
    with CaptureQueriesContext(connection) as few:
        client_a.get(url)
    for _ in range(6):
        extra = services.create_assessment(project, import_document(FULL).document)
        client_a.post(reverse("assessments:publish", args=[extra.pk]))
    with CaptureQueriesContext(connection) as many:
        client_a.get(url)
    assert len(many) == len(few)
