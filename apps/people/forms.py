"""Forms for the roster pages. Group choices are always built from the user's own groups."""

from __future__ import annotations

import re

from django import forms
from django.utils.translation import gettext_lazy as _

from . import importing, services
from .access import groups_for
from .models import Group, Student
from .names import normalize_name

PIN_RE = re.compile(r"^\d{3,8}$")


class GroupChoiceField(forms.ModelChoiceField):
    """Groups of one list; admins see several owners, so the owner is part of the label."""

    def __init__(self, *args, show_owner: bool = False, **kwargs):
        self.show_owner = show_owner
        super().__init__(*args, **kwargs)

    def label_from_instance(self, obj: Group) -> str:
        return f"{obj.name} ({obj.owner})" if self.show_owner else obj.name


def _clean_group_name(value: str) -> str:
    value = importing.clean(value)
    if not normalize_name(value):
        raise forms.ValidationError(_("Enter a name with letters or digits."))
    return value


def _clean_person_name(value: str) -> str:
    value = importing.clean(value)
    if not any(ch.isalpha() for ch in value):
        raise forms.ValidationError(_("Enter a name with letters."))
    return value


class GroupForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = ["name", "note", "is_archived"]
        labels = {
            "name": _("Group name"),
            "note": _("Note"),
            "is_archived": _("Archived (hidden from the list; students and results are kept)"),
        }
        widgets = {"note": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, owner, **kwargs):
        super().__init__(*args, **kwargs)
        self.owner = owner
        self.fields["name"].help_text = _("For example 7-A or Physics, evening course.")
        self.fields["note"].required = False
        if not self.instance.pk:
            del self.fields["is_archived"]  # nothing to archive yet

    def clean_name(self):
        name = _clean_group_name(self.cleaned_data["name"])
        if services.group_name_taken(self.owner.pk, name, exclude_pk=self.instance.pk):
            raise forms.ValidationError(_("You already have a group with this name."))
        return name


class StudentForm(forms.ModelForm):
    group = GroupChoiceField(
        queryset=Group.objects.none(),
        required=False,
        empty_label=_("No group"),
        label=_("Group"),
    )

    class Meta:
        model = Student
        fields = ["full_name", "group", "pin", "notes", "is_active"]
        labels = {
            "full_name": _("Full name"),
            "pin": _("PIN"),
            "notes": _("Notes"),
            "is_active": _("Active (untick when the student has left the class)"),
        }
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
            "pin": forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "off"}),
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        # An existing student can only move between groups of its own owner.
        groups = groups_for(user).select_related("owner")
        if self.instance.pk:
            groups = groups.filter(owner_id=self.instance.owner_id)
        self.fields["group"].queryset = groups
        self.fields["group"].show_owner = user.is_admin_role and not self.instance.pk
        self.fields["pin"].required = False
        self.fields["notes"].required = False
        if not self.instance.pk:
            del self.fields["is_active"]  # a new student is active
        self.fields["pin"].help_text = _(
            "Optional, 3 to 8 digits. Used to confirm identity in group sessions."
        )

    def clean_full_name(self):
        return _clean_person_name(self.cleaned_data["full_name"])

    def clean_pin(self):
        pin = self.cleaned_data.get("pin", "").strip()
        if pin and not PIN_RE.match(pin):
            raise forms.ValidationError(_("The PIN must be 3 to 8 digits."))
        return pin

    def clean(self):
        cleaned = super().clean()
        group, pin = cleaned.get("group"), cleaned.get("pin")
        if group is not None and pin:
            clash = Student.objects.filter(group=group, pin=pin).exclude(pk=self.instance.pk)
            if clash.exists():
                self.add_error("pin", _("Another student in this group already has this PIN."))
        return cleaned


class ImportForm(forms.Form):
    text = forms.CharField(
        required=False,
        label=_("Paste a list"),
        widget=forms.Textarea(attrs={"rows": 10, "spellcheck": "false", "autocomplete": "off"}),
    )
    file = forms.FileField(required=False, label=_("Or upload a CSV or XLSX file"))
    default_group = GroupChoiceField(
        queryset=Group.objects.none(),
        required=False,
        empty_label=_("No group"),
        label=_("Put students without a group into"),
    )
    new_group = forms.CharField(
        required=False,
        max_length=importing.MAX_GROUP_LENGTH,
        label=_("Or into a new group"),
        help_text=_("Created when you confirm. Leave empty to use the group above."),
    )

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["default_group"].queryset = groups_for(user).select_related("owner")
        self.fields["default_group"].show_owner = user.is_admin_role

    def clean_file(self):
        upload = self.cleaned_data.get("file")
        if upload is not None and upload.size > importing.MAX_BYTES:
            raise forms.ValidationError(_("The file is too large (limit 2 MB)."))
        return upload

    def clean(self):
        cleaned = super().clean()
        text = (cleaned.get("text") or "").strip()
        upload = cleaned.get("file")
        if self.errors:
            return cleaned
        if text and upload:
            raise forms.ValidationError(_("Use the text box or a file, not both."))
        if not text and not upload:
            raise forms.ValidationError(_("Paste a list of names or choose a file."))
        if cleaned.get("default_group") and importing.clean(cleaned.get("new_group")):
            raise forms.ValidationError(
                _("Choose an existing group or type a new group name, not both.")
            )
        return cleaned
