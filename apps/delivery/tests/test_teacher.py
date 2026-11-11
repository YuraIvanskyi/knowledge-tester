import pytest
from django.urls import reverse

from apps.core import lan
from apps.delivery import services
from apps.delivery.models import CODE_ALPHABET, CODE_LENGTH, Attempt, Sitting

from .conftest import make_revision, start

pytestmark = pytest.mark.django_db


def test_create_session_flow(client, teacher, revision):
    client.force_login(teacher)
    url = reverse("delivery:create", args=[revision.pk])
    page = client.get(url)
    assert page.status_code == 200 and 'value="Fractions"' in page.content.decode()
    r = client.post(url, {"title": "7-A, Monday", "access_code": "abc"})
    sitting = Sitting.objects.get()
    assert r.status_code == 302 and r["Location"] == reverse("delivery:share", args=[sitting.pk])
    assert sitting.title == "7-A, Monday" and sitting.access_code == "abc"
    assert sitting.created_by == teacher and sitting.revision == revision
    assert len(sitting.code) == CODE_LENGTH and set(sitting.code) <= set(CODE_ALPHABET)


def test_create_requires_title(client, teacher, revision):
    client.force_login(teacher)
    r = client.post(reverse("delivery:create", args=[revision.pk]), {"title": ""})
    assert r.status_code == 200 and Sitting.objects.count() == 0


def test_create_for_foreign_revision_404(client, other_teacher, revision, admin_user):
    client.force_login(other_teacher)
    assert client.get(reverse("delivery:create", args=[revision.pk])).status_code == 404
    assert (
        client.post(reverse("delivery:create", args=[revision.pk]), {"title": "x"}).status_code
        == 404
    )
    client.force_login(admin_user)
    assert client.get(reverse("delivery:create", args=[revision.pk])).status_code == 200


def test_login_required(client, sitting, revision):
    for name, args in [
        ("delivery:list", []),
        ("delivery:create", [revision.pk]),
        ("delivery:share", [sitting.pk]),
        ("delivery:stats", [sitting.pk]),
        ("delivery:close", [sitting.pk]),
    ]:
        r = client.get(reverse(name, args=args))
        assert r.status_code == 302 and "/accounts/login/" in r["Location"], name


def test_ownership_404(client, sitting, other_teacher, admin_user):
    client.force_login(other_teacher)
    for name in ("delivery:share", "delivery:stats"):
        assert client.get(reverse(name, args=[sitting.pk])).status_code == 404
    assert client.post(reverse("delivery:close", args=[sitting.pk])).status_code == 404
    sitting.refresh_from_db()
    assert sitting.status == Sitting.Status.OPEN
    # the list only shows my own sessions
    assert sitting.code not in client.get(reverse("delivery:list")).content.decode()
    client.force_login(admin_user)
    assert client.get(reverse("delivery:share", args=[sitting.pk])).status_code == 200
    assert sitting.code in client.get(reverse("delivery:list")).content.decode()


def test_list(client, teacher, sitting):
    start(client, sitting)  # an attempt from a taker
    client.force_login(teacher)
    html = client.get(reverse("delivery:list")).content.decode()
    assert sitting.code in html and "7-A" in html and "Fractions" in html
    assert reverse("delivery:share", args=[sitting.pk]) in html
    assert reverse("reports:session", args=[sitting.pk]) in html


def test_share_page(client, teacher, sitting, monkeypatch):
    monkeypatch.setattr(lan, "lan_ipv4_addresses", lambda: ["192.168.1.23"])
    client.force_login(teacher)
    r = client.get(reverse("delivery:share", args=[sitting.pk]))
    html = r.content.decode()
    assert r.status_code == 200
    assert f"http://192.168.1.23:80/s/{sitting.code}/" in html or (
        f"http://192.168.1.23:{r.wsgi_request.get_port()}/s/{sitting.code}/" in html
    )
    assert "<svg" in html and "segno" in html
    assert "style=" not in html
    assert "http://www.w3.org" not in html.replace("</svg>", "")
    assert 'class="big-code"' in html and sitting.code in html
    assert 'data-stats-url="' in html and "js/share.js" in html
    assert "Close session" in html


def test_share_pick_ip(client, teacher, sitting, monkeypatch):
    monkeypatch.setattr(lan, "lan_ipv4_addresses", lambda: ["192.168.1.23", "10.0.0.5"])
    client.force_login(teacher)
    url = reverse("delivery:share", args=[sitting.pk])
    assert "192.168.1.23" in client.get(url).content.decode()
    html = client.get(url + "?ip=10.0.0.5").content.decode()
    assert "://10.0.0.5:" in html and 'href="?ip=192.168.1.23"' in html
    # remembered, and unknown addresses are ignored
    assert "://10.0.0.5:" in client.get(url).content.decode()
    assert "://10.0.0.5:" in client.get(url + "?ip=8.8.8.8").content.decode()


def test_stats_endpoint(client, teacher, sitting):
    from django.test import Client

    for name in ("Ann", "Bob", "Cy"):
        c = Client()
        start(c, sitting, name=name)
        if name == "Bob":
            c.post(
                f"/s/{sitting.code}/save/",
                data='{"answers": {"q1": ["a"]}}',
                content_type="application/json",
            )
            c.post(f"/s/{sitting.code}/submit/", {"form_sent": "1", "q_q1": "a", "q_q4": "x"})
    client.force_login(teacher)
    data = client.get(reverse("delivery:stats", args=[sitting.pk])).json()
    assert (data["joined"], data["in_progress"], data["submitted"]) == (3, 2, 1)
    assert data["total_questions"] == 5 and data["status"] == "open"
    bob = next(t for t in data["takers"] if t["name"] == "Bob")
    assert bob["answered"] == 2 and bob["status"] == "submitted"
    ann = next(t for t in data["takers"] if t["name"] == "Ann")
    assert ann["answered"] == 0 and ann["status"] == "in_progress"


def test_close_finalizes_in_progress(client, teacher, sitting, grade_calls):
    from django.test import Client

    t1, t2 = Client(), Client()
    start(t1, sitting, name="Ann")
    start(t2, sitting, name="Bob")
    t1.post(
        f"/s/{sitting.code}/save/",
        data='{"answers": {"q1": ["a"]}}',
        content_type="application/json",
    )
    t2.post(f"/s/{sitting.code}/submit/", {"form_sent": "1", "q_q1": "a"})
    assert len(grade_calls) == 1

    client.force_login(teacher)
    r = client.get(reverse("delivery:close", args=[sitting.pk]))
    assert r.status_code == 405  # POST only
    r = client.post(reverse("delivery:close", args=[sitting.pk]))
    assert r["Location"] == reverse("delivery:share", args=[sitting.pk])
    sitting.refresh_from_db()
    assert sitting.status == Sitting.Status.CLOSED and sitting.closed_at
    ann = sitting.attempts.get(taker__name="Ann")
    bob = sitting.attempts.get(taker__name="Bob")
    assert ann.status == Attempt.Status.AUTO_SUBMITTED and ann.submitted_at
    assert ann.score == 1 and ann.max_score == 9  # graded from autosaved answers
    assert bob.status == Attempt.Status.SUBMITTED
    assert len(grade_calls) == 2
    # closed again: nothing breaks, nothing re-graded
    client.post(reverse("delivery:close", args=[sitting.pk]))
    assert len(grade_calls) == 2
    # share page after closing links to results and hides QR
    html = client.get(reverse("delivery:share", args=[sitting.pk])).content.decode()
    assert "Close session" not in html and reverse("reports:session", args=[sitting.pk]) in html
    # taker sees done page
    assert t1.get(f"/s/{sitting.code}/take/")["Location"].endswith("/done/")


def test_codes_are_unique_and_valid(teacher, revision, monkeypatch):
    codes = {services.generate_code() for _ in range(200)}
    assert all(len(c) == CODE_LENGTH and set(c) <= set(CODE_ALPHABET) for c in codes)

    first = services.create_sitting(revision=revision, user=teacher, title="a")
    produced = iter([first.code, first.code, "AAAAAA"])
    monkeypatch.setattr(services, "generate_code", lambda: next(produced))
    second = services.create_sitting(revision=revision, user=teacher, title="b")
    assert second.code == "AAAAAA" != first.code


def test_other_users_revision_not_leaked_between_projects(client, teacher, other_teacher):
    foreign = make_revision(other_teacher)
    client.force_login(teacher)
    assert client.get(reverse("delivery:create", args=[foreign.pk])).status_code == 404
