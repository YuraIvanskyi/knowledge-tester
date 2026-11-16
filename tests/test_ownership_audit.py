"""Ownership audit (KT-607): every teacher URL, hit by someone who does not own the object.

The URL list is read from the resolver, so a new route under ``/teach/`` that is not described in
``ARGS`` fails ``test_every_teacher_route_is_audited``: whoever adds a route has to say which
object it addresses, and then it is checked here automatically.

Rules checked:
* anonymous -> redirect to the login page, for every route and method;
* another teacher -> 404 for every route that addresses an object, for GET and POST, and no page
  that lists things shows the first teacher's data;
* an admin is not turned away by the ownership check (no 404 on GET).
"""

import copy
import re

import pytest
from django.urls import get_resolver, reverse

from apps.assessments.models import Assessment, Project, Revision
from apps.delivery import services
from apps.people.models import Group, Student

PASSWORD = "pw-for-tests-123"
SECRET = "ZZSECRET"  # appears in every name the owner creates; must never reach another teacher

DOCUMENT = {
    "format": "knowledge-tester/test",
    "version": 1,
    "test": {
        "title": f"{SECRET} test",
        "language": "en",
        "settings": {"max_attempts": 3},
        "taker_fields": [{"key": "name", "label": "Full name", "required": True}],
        "grading": {"enabled": True, "scale": "percent"},
        "questions": [
            {
                "id": "q1",
                "type": "single_choice",
                "text": "Pick one",
                "points": 1,
                "options": [
                    {"id": "a", "text": "yes", "correct": True},
                    {"id": "b", "text": "no"},
                ],
            }
        ],
    },
}

# URL name -> {url kwarg: object kind}; kinds are resolved in the ``world`` fixture.
ARGS: dict[str, dict[str, str]] = {
    # Pages that address no object (their lists must be scoped to the viewer).
    "core:dashboard": {},
    "core:help": {},
    "assessments:list": {},
    "assessments:create": {},
    "assessments:import": {},
    "delivery:list": {},
    "delivery:pick": {},
    "people:groups": {},
    "people:group_create": {},
    "people:students": {},
    "people:student_create": {},
    "people:import": {},
    "people:import_confirm": {},
    # Tests
    "assessments:detail": {"pk": "assessment"},
    "assessments:publish": {"pk": "assessment"},
    "assessments:delete": {"pk": "assessment"},
    "assessments:preview": {"pk": "assessment"},
    "assessments:export": {"pk": "assessment"},
    "assessments:settings": {"pk": "assessment"},
    "assessments:variant_add": {"pk": "assessment"},
    "assessments:variant_delete": {"pk": "assessment", "variant_id": "text:v1"},
    "assessments:question_new": {"pk": "assessment", "question_type": "text:single_choice"},
    "assessments:question_edit": {"pk": "assessment", "question_id": "text:q1"},
    "assessments:question_delete": {"pk": "assessment", "question_id": "text:q1"},
    "assessments:question_move": {"pk": "assessment", "question_id": "text:q1"},
    "assessments:question_duplicate": {"pk": "assessment", "question_id": "text:q1"},
    # Sessions
    "delivery:create": {"revision_pk": "revision"},
    "delivery:share": {"pk": "sitting"},
    "delivery:stats": {"pk": "sitting"},
    "delivery:close": {"pk": "sitting"},
    "delivery:extend": {"pk": "sitting"},
    "delivery:reopen": {"pk": "sitting"},
    "delivery:delete": {"pk": "sitting"},
    "delivery:link": {"pk": "sitting"},
    # People
    "people:group": {"pk": "group"},
    "people:group_edit": {"pk": "group"},
    "people:group_delete": {"pk": "group"},
    "people:group_pins": {"pk": "group"},
    "people:gradebook": {"pk": "group"},
    "people:gradebook_csv": {"pk": "group"},
    "people:student": {"pk": "student"},
    "people:student_edit": {"pk": "student"},
    "people:student_notes": {"pk": "student"},
    "people:student_delete": {"pk": "student"},
    "people:student_csv": {"pk": "student"},
    "people:student_pdf": {"pk": "student"},
    # Results
    "reports:session": {"sitting_pk": "sitting"},
    "reports:csv": {"sitting_pk": "sitting"},
    "reports:session_pdf": {"sitting_pk": "sitting"},
    "reports:attempt": {"pk": "attempt"},
    "reports:attempt_void": {"pk": "attempt"},
    "reports:attempt_pdf": {"pk": "attempt"},
}


def _teacher_routes() -> list[str]:
    """Every named route whose path starts with teach/ (namespace:name)."""

    def walk(patterns, prefix="", namespace=""):
        for p in patterns:
            if hasattr(p, "url_patterns"):
                ns = namespace + (p.namespace + ":" if p.namespace else "")
                yield from walk(p.url_patterns, prefix + str(p.pattern), ns)
            else:
                yield namespace + (p.name or ""), prefix + str(p.pattern)

    return sorted({n for n, path in walk(get_resolver().url_patterns) if path.startswith("teach")})


@pytest.fixture
def owner(django_user_model):
    return django_user_model.objects.create_user("owner", password=PASSWORD, role="teacher")


@pytest.fixture
def stranger(django_user_model):
    return django_user_model.objects.create_user("stranger", password=PASSWORD, role="teacher")


@pytest.fixture
def boss(django_user_model):
    return django_user_model.objects.create_superuser("boss", password=PASSWORD)


@pytest.fixture
def world(owner):
    """One of everything, all owned by ``owner``."""
    project = Project.objects.create(owner=owner, title=f"{SECRET} project")
    # The draft has two variants (the published revision has none), so the variant routes have
    # something to address; "q1" is still there, inside variant "v1".
    draft = copy.deepcopy(DOCUMENT)
    questions = draft["test"].pop("questions")
    second = copy.deepcopy(questions)
    for number, question in enumerate(second, start=1):
        question["id"] = f"w{number}"
    draft["test"]["variants"] = [
        {"id": "v1", "title": f"{SECRET} variant", "questions": questions},
        {"id": "v2", "title": "", "questions": second},
    ]
    assessment = Assessment.objects.create(project=project, title=f"{SECRET} test", document=draft)
    revision = Revision.objects.create(
        assessment=assessment, number=1, document=DOCUMENT, content_hash="x", created_by=owner
    )
    group = Group.objects.create(owner=owner, name=f"{SECRET} class")
    student = Student.objects.create(
        owner=owner, group=group, full_name=f"{SECRET} Pupil", pin="1234", notes=f"{SECRET} note"
    )
    sitting = services.create_sitting(
        revision=revision, user=owner, title=f"{SECRET} session", group=group
    )
    attempt = services.start_attempt(sitting, {"name": f"{SECRET} Pupil"}, student=student)
    services.finalize(attempt)
    return {
        "assessment": assessment,
        "revision": revision,
        "group": group,
        "student": student,
        "sitting": sitting,
        "attempt": attempt,
    }


NO_SUCH_ID = 999_999


def url_for(name: str, world, missing: bool = False) -> str:
    """The URL of the audited object, or (missing=True) the same URL with ids that do not exist."""
    kwargs = {}
    for arg, kind in ARGS[name].items():
        if kind.startswith("text:"):
            kwargs[arg] = kind.split(":", 1)[1]
        else:
            kwargs[arg] = NO_SUCH_ID if missing else world[kind].pk
    return reverse(name, kwargs=kwargs)


def test_every_teacher_route_is_audited():
    routes = _teacher_routes()
    missing = [n for n in routes if n not in ARGS]
    assert not missing, f"describe these routes in ARGS: {missing}"
    stale = [n for n in ARGS if n not in routes]
    assert not stale, f"ARGS names routes that no longer exist: {stale}"


@pytest.mark.parametrize("method", ["get", "post"])
@pytest.mark.parametrize("name", sorted(ARGS))
def test_anonymous_is_sent_to_login(client, world, name, method):
    url = url_for(name, world)
    response = getattr(client, method)(url)
    assert response.status_code == 302, (name, response.status_code)
    assert response["Location"].startswith(reverse("accounts:login")), (name, response["Location"])


OBJECT_ROUTES = sorted(n for n, args in ARGS.items() if args)
LIST_ROUTES = sorted(n for n, args in ARGS.items() if not args)


@pytest.mark.parametrize("method", ["get", "post"])
@pytest.mark.parametrize("name", OBJECT_ROUTES)
def test_another_teachers_object_is_indistinguishable_from_a_missing_one(
    client, stranger, world, name, method
):
    """404 (or 405 where the route does not take this method): the same answer an id that does not
    exist gets, so the response never reveals that somebody else's object is there."""
    client.force_login(stranger)
    foreign = getattr(client, method)(url_for(name, world))
    missing = getattr(client, method)(url_for(name, world, missing=True))
    assert foreign.status_code in (404, 405), (name, method, foreign.status_code)
    assert foreign.status_code == missing.status_code, (name, method)
    assert SECRET.encode() not in foreign.content


@pytest.mark.parametrize("name", LIST_ROUTES)
def test_pages_without_an_object_show_nothing_of_anothers(client, stranger, world, name):
    client.force_login(stranger)
    response = client.get(reverse(name))
    assert response.status_code in (200, 302, 405), (name, response.status_code)
    assert SECRET.encode() not in response.content, name


@pytest.mark.parametrize("name", [n for n in OBJECT_ROUTES if n not in {"delivery:create"}])
def test_admin_is_not_stopped_by_ownership_on_get(client, boss, world, name):
    client.force_login(boss)
    response = client.get(url_for(name, world))
    assert response.status_code != 404, name
    assert response.status_code < 500, (name, response.status_code)


def test_owner_still_gets_their_own_pages(client, owner, world):
    """Guards the audit itself: if the owner got 404s too, the checks above would prove nothing."""
    client.force_login(owner)
    for name in ["assessments:detail", "delivery:share", "people:group", "people:student"]:
        assert client.get(url_for(name, world)).status_code == 200, name
    assert re.search(SECRET, client.get(reverse("assessments:list")).content.decode())
