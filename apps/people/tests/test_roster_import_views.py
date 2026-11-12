"""The import wizard: paste / CSV / XLSX -> preview -> confirm."""

import io
import re
import sys

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from apps.people import importing
from apps.people.models import Group, Student

pytestmark = pytest.mark.django_db

IMPORT = "people:import"
CONFIRM = "people:import_confirm"


def messages_of(response):
    return [str(m) for m in response.context["messages"]]


def token_of(response):
    return re.search(r'name="token" value="([0-9a-f]+)"', response.content.decode()).group(1)


def start(tc, text="", file=None, **extra):
    data = {"text": text, **extra}
    if file is not None:
        data["file"] = file
    return tc.post(reverse(IMPORT), data)


def preview_of(tc, text="", file=None, **extra):
    response = start(tc, text, file, **extra)
    assert response.status_code == 302, response.content.decode()[:2000]
    assert response["Location"] == reverse(IMPORT) + "?step=preview"
    return tc.get(response["Location"])


def confirm(tc, preview, **fields):
    return tc.post(reverse(CONFIRM), {"token": token_of(preview), **fields}, follow=True)


def upload(name, content, content_type="application/octet-stream"):
    return SimpleUploadedFile(name, content, content_type=content_type)


def xlsx_bytes(rows):
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    sheet = book.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


@pytest.fixture
def tc(client_for, teacher):
    return client_for(teacher)


# ---- the form --------------------------------------------------------------------------------


def test_import_form_renders(tc):
    response = tc.get(reverse(IMPORT))
    html = response.content.decode()
    assert response.status_code == 200
    assert 'enctype="multipart/form-data"' in html and 'name="text"' in html
    assert 'name="file"' in html and 'name="default_group"' in html and 'name="new_group"' in html


def test_group_query_preselects_only_my_groups(tc, teacher, other_teacher):
    mine = Group.objects.create(owner=teacher, name="7-А")
    theirs = Group.objects.create(owner=other_teacher, name="8-Б")
    page = tc.get(reverse(IMPORT) + f"?group={mine.pk}")
    assert page.context["form"].initial["default_group"] == mine.pk
    page = tc.get(reverse(IMPORT) + f"?group={theirs.pk}")
    assert "default_group" not in page.context["form"].initial
    assert "8-Б" not in page.content.decode()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({}, "Paste a list of names or choose a file."),
        ({"text": "   \n  "}, "Paste a list of names or choose a file."),
        ({"text": ";;;\n\n"}, "No names were found"),
    ],
)
def test_empty_input_is_refused(tc, kwargs, message):
    response = start(tc, **kwargs)
    assert response.status_code == 200
    assert message in response.content.decode()
    assert Student.objects.count() == 0


def test_text_and_file_together_are_refused(tc):
    response = start(tc, "Іван Петренко", upload("a.csv", b"Name\nX Y"))
    assert response.status_code == 200
    assert "Use the text box or a file, not both." in response.content.decode()


def test_group_and_new_group_together_are_refused(tc, teacher):
    group = Group.objects.create(owner=teacher, name="7-А")
    response = start(tc, "Іван Петренко", default_group=group.pk, new_group="Нова")
    assert response.status_code == 200
    assert "not both" in response.content.decode()


def test_default_group_must_be_mine(tc, other_teacher):
    theirs = Group.objects.create(owner=other_teacher, name="8-Б")
    response = start(tc, "Іван Петренко", default_group=theirs.pk)
    assert response.status_code == 200
    assert "default_group" in response.context["form"].errors
    assert Student.objects.count() == 0


# ---- paste -> preview -> confirm -------------------------------------------------------------


def test_paste_preview_and_confirm_happy_path(tc, teacher):
    text = "1. Іваненко Петро; 7-А\n2. Коваль Дем’ян; 7-А\n3. Мельник Олена; 7-Б\nШевченко Софія"
    preview = preview_of(tc, text)
    html = preview.content.decode()
    assert preview.status_code == 200
    for name in ("Іваненко Петро", "Коваль Дем’ян", "Мельник Олена", "Шевченко Софія"):
        assert name in html
    assert html.count("(new group)") == 3  # every row that uses a new group
    assert "These groups will be created:" in html
    assert 'action="' + reverse(CONFIRM) + '"' in html
    assert html.count('name="include"') == 4
    assert 'name="skip_duplicates"' in html and "checked" in html
    assert Student.objects.count() == 0  # nothing saved by the preview

    done = confirm(tc, preview, include=["0", "1", "2", "3"], skip_duplicates="1")
    assert Student.objects.count() == 4
    assert sorted(Group.objects.values_list("name", flat=True)) == ["7-А", "7-Б"]
    assert Student.objects.get(full_name="Коваль Дем’ян").group.name == "7-А"
    assert Student.objects.get(full_name="Шевченко Софія").group is None
    assert all(s.owner == teacher for s in Student.objects.all())
    assert done.redirect_chain[-1][0] == reverse("people:groups")  # several groups involved
    assert "4 students added. 2 groups created." in messages_of(done)


def test_confirm_goes_to_the_group_page_when_everyone_is_in_one_group(tc, teacher):
    group = Group.objects.create(owner=teacher, name="7-А")
    preview = preview_of(tc, "А Один\nБ Два", default_group=group.pk)
    assert "Rows without a group go into" in preview.content.decode()
    done = confirm(tc, preview, include=["0", "1"], skip_duplicates="1")
    assert done.redirect_chain[-1][0] == reverse("people:group", args=[group.pk])
    assert group.students.count() == 2
    assert "2 students added." in messages_of(done)


def test_new_group_for_the_whole_list(tc, teacher):
    preview = preview_of(tc, "А Один\nБ Два; Інша", new_group=" Гурток ")
    html = preview.content.decode()
    assert "Rows without a group go into the new group" in html and "Гурток" in html
    confirm(tc, preview, include=["0", "1"], skip_duplicates="1")
    assert set(Group.objects.values_list("name", flat=True)) == {"Гурток", "Інша"}
    assert Student.objects.get(full_name="А Один").group.name == "Гурток"


def test_preview_marks_duplicates_and_invalid_rows(tc, teacher):
    group = Group.objects.create(owner=teacher, name="7-А")
    Student.objects.create(owner=teacher, group=group, full_name="Іваненко Дем’ян")
    text = "Нова Людина\nДем'ян Іваненко\nІваненко  Дем'ян\nНова Людина\n12345\nЄ Ще"
    preview = preview_of(tc, text)
    html = preview.content.decode()
    assert html.count("Possible duplicate</span>") == 3
    assert "same person as Іваненко Дем’ян (7-А)" in html
    assert "same words in a different order" in html
    assert "same person as Нова Людина (row 1 of this list)" in html
    assert "Not valid</span>: the name has no letters" in html
    assert (preview.context["preview"].n_new, preview.context["preview"].n_duplicate) == (2, 3)
    assert preview.context["preview"].n_invalid == 1
    assert "1 not valid" in html and "3 duplicates" in html


def test_duplicates_are_skipped_by_default(tc, teacher):
    Student.objects.create(owner=teacher, full_name="Іваненко Петро")
    preview = preview_of(tc, "Петро Іваненко\nКоваль Олена\n12345")
    done = confirm(tc, preview, include=["0", "1"], skip_duplicates="1")
    assert sorted(Student.objects.values_list("full_name", flat=True)) == [
        "Іваненко Петро",
        "Коваль Олена",
    ]
    msgs = messages_of(done)
    assert "1 student added." in msgs
    assert any(
        "1 duplicate skipped." in m and "1 row that is not valid was skipped." in m for m in msgs
    )


def test_duplicates_can_be_added_by_unticking_the_switch(tc, teacher):
    Student.objects.create(owner=teacher, full_name="Іваненко Петро")
    preview = preview_of(tc, "Петро Іваненко\nКоваль Олена")
    confirm(tc, preview, include=["0", "1"])  # skip_duplicates not sent = unticked
    assert Student.objects.count() == 3


def test_unticked_rows_are_not_added(tc, teacher):
    preview = preview_of(tc, "А Один; Нова\nБ Два; Нова\nВ Три; Інша")
    done = confirm(tc, preview, include=["1"], skip_duplicates="1")
    assert list(Student.objects.values_list("full_name", flat=True)) == ["Б Два"]
    assert list(Group.objects.values_list("name", flat=True)) == ["Нова"]  # Інша was not needed
    assert any("2 rows you unticked were skipped." in m for m in messages_of(done))


def test_tampered_include_values_cannot_add_invalid_or_unknown_rows(tc, teacher):
    preview = preview_of(tc, "А Один\n12345")
    confirm(tc, preview, include=["0", "1", "7", "-1", "abc", "1; DROP"], skip_duplicates="1")
    assert list(Student.objects.values_list("full_name", flat=True)) == ["А Один"]


def test_nothing_to_add_keeps_the_preview(tc):
    preview = preview_of(tc, "А Один\nБ Два")
    done = confirm(tc, preview, skip_duplicates="1")  # everything unticked
    assert Student.objects.count() == 0
    assert any("Nothing was added" in m for m in messages_of(done))
    assert done.redirect_chain[-1][0] == reverse(IMPORT) + "?step=preview"
    assert "А Один" in done.content.decode()  # still there to try again


def test_all_rows_invalid_shows_no_confirm_form(tc):
    preview = preview_of(tc, "12345\n6789")
    html = preview.content.decode()
    assert "Nothing in this list can be added." in html
    assert 'name="include"' not in html and reverse(CONFIRM) not in html


def test_edit_the_list_prefills_the_text(tc):
    preview = preview_of(tc, "А Один; 7-А\nБ Два")
    assert "?back=1" in preview.content.decode()
    form = tc.get(reverse(IMPORT) + "?back=1")
    assert form.context["form"].initial["text"] == "А Один; 7-А\nБ Два"
    assert "А Один" not in tc.get(reverse(IMPORT)).content.decode()


# ---- confirm safety --------------------------------------------------------------------------


def test_confirm_is_post_only(tc):
    assert tc.get(reverse(CONFIRM)).status_code == 405


def test_confirm_without_a_preview_does_nothing(tc):
    done = tc.post(reverse(CONFIRM), {"token": "x", "include": ["0"]}, follow=True)
    assert Student.objects.count() == 0
    assert "This preview is out of date. Start the import again." in messages_of(done)


def test_confirm_needs_the_matching_token_and_works_only_once(tc):
    preview = preview_of(tc, "А Один")
    bad = tc.post(reverse(CONFIRM), {"token": "nope", "include": ["0"]}, follow=True)
    assert Student.objects.count() == 0
    assert "out of date" in messages_of(bad)[0]
    first = confirm(tc, preview, include=["0"], skip_duplicates="1")
    assert Student.objects.count() == 1
    again = tc.post(reverse(CONFIRM), {"token": token_of(preview), "include": ["0"]}, follow=True)
    assert Student.objects.count() == 1  # the stored list was consumed
    assert "out of date" in messages_of(again)[0] and first


def test_a_new_upload_replaces_the_pending_preview(tc):
    old = preview_of(tc, "Старий Список")
    new = preview_of(tc, "Новий Список")
    stale = tc.post(reverse(CONFIRM), {"token": token_of(old), "include": ["0"]}, follow=True)
    assert Student.objects.count() == 0 and "out of date" in messages_of(stale)[0]
    confirm(tc, new, include=["0"], skip_duplicates="1")
    assert list(Student.objects.values_list("full_name", flat=True)) == ["Новий Список"]


def test_the_preview_belongs_to_the_session_of_the_teacher_who_made_it(
    tc, client_for, other_teacher
):
    preview = preview_of(tc, "А Один")
    token = token_of(preview)
    thief = Client()
    thief.force_login(other_teacher)
    done = thief.post(reverse(CONFIRM), {"token": token, "include": ["0"]}, follow=True)
    assert Student.objects.count() == 0 and "out of date" in messages_of(done)[0]


def test_group_deleted_between_preview_and_confirm(tc, teacher):
    group = Group.objects.create(owner=teacher, name="7-А")
    preview = preview_of(tc, "А Один", default_group=group.pk)
    group.delete()
    done = confirm(tc, preview, include=["0"], skip_duplicates="1")
    assert Student.objects.count() == 0
    assert "The chosen group no longer exists. Start again." in messages_of(done)


def test_preview_is_rechecked_at_confirm_time(tc, teacher):
    preview = preview_of(tc, "А Один\nБ Два")
    Student.objects.create(owner=teacher, full_name="Один А")  # appears meanwhile
    done = confirm(tc, preview, include=["0", "1"], skip_duplicates="1")
    assert set(Student.objects.values_list("full_name", flat=True)) == {"Один А", "Б Два"}
    assert any("1 duplicate skipped." in m for m in messages_of(done))


def test_preview_without_pending_import_redirects(tc):
    response = tc.get(reverse(IMPORT) + "?step=preview", follow=True)
    assert response.redirect_chain[-1][0] == reverse(IMPORT)
    assert "There is nothing to check" in messages_of(response)[0]


def test_other_teachers_groups_are_not_matched_by_name(tc, teacher, other_teacher):
    theirs = Group.objects.create(owner=other_teacher, name="7-А")
    preview = preview_of(tc, "А Один; 7-А")
    assert "(new group)" in preview.content.decode()
    confirm(tc, preview, include=["0"], skip_duplicates="1")
    mine = Student.objects.get().group
    assert mine.owner == teacher and mine.pk != theirs.pk
    assert theirs.students.count() == 0


# ---- CSV and XLSX ----------------------------------------------------------------------------


def test_csv_upload_utf8_and_cp1251(tc):
    csv_text = "Прізвище;Ім'я;Клас\nІваненко;Петро;7-А\nКоваль;Олена;7-Б\n"
    for encoded in (csv_text.encode("utf-8-sig"), csv_text.encode("cp1251")):
        preview = preview_of(tc, file=upload("class.csv", encoded, "text/csv"))
        html = preview.content.decode()
        assert "Іваненко Петро" in html and "Коваль Олена" in html
        assert (
            "Edit the list" not in html and "Start again" in html
        )  # an upload has no text to edit
    confirm(tc, preview, include=["0", "1"], skip_duplicates="1")
    assert Student.objects.get(full_name="Іваненко Петро").group.name == "7-А"


def test_file_names_are_not_trusted(tc):
    xlsx = xlsx_bytes([["Name", "Group"], ["Іван Петренко", "7-А"]])
    for name in ("list.csv", "../../etc/passwd", "list.txt", ""):
        preview = preview_of(tc, file=upload(name or "x", xlsx))
        assert "Іван Петренко" in preview.content.decode()
    csv_as_xlsx = preview_of(tc, file=upload("list.xlsx", "Name\nІван Петренко".encode()))
    assert "Іван Петренко" in csv_as_xlsx.content.decode()


def test_xlsx_upload(tc):
    data = xlsx_bytes(
        [
            ["№", "ПІБ", "Клас"],
            [1, "Іваненко Петро Іванович", "7-А"],
            [2, "Коваль Дем'ян", "7-А"],
            [3, "Мельник-Шевченко Олена", 8],
        ]
    )
    preview = preview_of(tc, file=upload("class.xlsx", data))
    html = preview.content.decode()
    assert "Іваненко Петро Іванович" in html and "Мельник-Шевченко Олена" in html
    confirm(tc, preview, include=["0", "1", "2"], skip_duplicates="1")
    assert Student.objects.count() == 3
    assert Student.objects.get(full_name="Мельник-Шевченко Олена").group.name == "8"


def test_xlsx_with_a_formula_is_read_as_values_only(tc):
    data = xlsx_bytes([["Name", "Group"], ["=1+1", "7-А"], ["Іван Петренко", "7-А"]])
    preview = preview_of(tc, file=upload("class.xlsx", data))
    html = preview.content.decode()
    assert "Not valid</span>: the name is empty" in html and "Іван Петренко" in html


def test_bad_uploads_give_plain_messages(tc):
    cases = [
        (b"PK\x03\x04junk", "could not be read as an Excel workbook"),
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 50, "Old .xls files are not supported"),
        (b"Name\x00\x01\x02", "does not look like a text or CSV file"),
        (b"", None),
    ]
    for content, message in cases:
        response = start(tc, file=upload("f.dat", content))
        assert response.status_code == 200
        if message:
            assert message in response.content.decode()
    assert Student.objects.count() == 0


def test_oversized_upload_is_refused(tc, monkeypatch):
    monkeypatch.setattr(importing, "MAX_BYTES", 100)
    response = start(tc, file=upload("big.csv", b"Name\n" + b"x" * 200))
    assert response.status_code == 200
    assert "The file is too large (limit 2 MB)." in response.content.decode()


def test_oversized_text_is_refused(tc, monkeypatch):
    monkeypatch.setattr(importing, "MAX_BYTES", 100)
    response = start(tc, "я" * 200)
    assert "too large" in response.content.decode()


def test_xlsx_without_the_extra_installed_shows_a_message(tc, monkeypatch):
    monkeypatch.setitem(sys.modules, "openpyxl", None)
    response = start(tc, file=upload("class.xlsx", b"PK\x03\x04"))
    assert response.status_code == 200
    assert "optional xlsx component" in response.content.decode()


def test_too_many_rows(tc):
    text = "\n".join(f"Учень {i}" for i in range(importing.MAX_ROWS + 1))
    response = start(tc, text)
    assert response.status_code == 200 and "Too many rows" in response.content.decode()


def test_a_long_list_has_no_per_row_checkboxes_but_imports_every_valid_row(tc):
    count = 850  # more than fits into the 1000 fields a POST may carry
    preview = preview_of(tc, "\n".join(f"Учень {i}" for i in range(count)) + "\n12345")
    html = preview.content.decode()
    assert 'name="include"' not in html and "rows cannot be unticked" in html
    confirm(tc, preview, skip_duplicates="1")
    assert Student.objects.count() == count


# ---- ownership -------------------------------------------------------------------------------


def test_admin_importing_into_a_teachers_group_keeps_the_teachers_roster(
    client_for, admin_user, teacher
):
    group = Group.objects.create(owner=teacher, name="7-А")
    admin_client = client_for(admin_user)
    preview = preview_of(admin_client, "А Один; Нова", default_group=group.pk)
    confirm(admin_client, preview, include=["0"], skip_duplicates="1")
    student = Student.objects.get()
    assert student.owner == teacher and student.group.owner == teacher


def test_teacher_cannot_import_into_a_foreign_group_via_the_session(tc, teacher, other_teacher):
    theirs = Group.objects.create(owner=other_teacher, name="8-Б")
    session = tc.session
    session["roster_import"] = {
        "token": "abc",
        "rows": [{"n": "Підкинутий Учень", "g": "", "i": []}],
        "default_group": theirs.pk,
        "new_group": "",
        "source": "paste",
        "text": "",
    }
    session.save()
    done = tc.post(reverse(CONFIRM), {"token": "abc", "include": ["0"]}, follow=True)
    assert Student.objects.count() == 0
    assert "no longer exists" in messages_of(done)[0]
