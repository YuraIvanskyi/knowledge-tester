from django import forms
from django.db.models import Count, Q
from django.utils.translation import gettext, ngettext
from django.utils.translation import gettext_lazy as _

from apps.people.models import Group


class GroupChoiceField(forms.ModelChoiceField):
    """The user's classes, each labelled with its size and how many students have no PIN."""

    def label_from_instance(self, obj):
        label = ngettext(
            "%(name)s (%(n)d student)", "%(name)s (%(n)d students)", obj.active_count
        ) % {"name": obj.name, "n": obj.active_count}
        if obj.no_pin_count:
            label += ", " + gettext("%(n)d without a PIN") % {"n": obj.no_pin_count}
        return label


def group_from_query(raw, user):
    """The user's own, non-archived class named by a `?group=<pk>` value, else None.

    A malformed, foreign or archived id is ignored silently (no 404, nothing leaks).
    """
    if user is None or not str(raw or "").isdecimal() or len(str(raw)) > 9:
        return None
    return Group.objects.filter(pk=int(raw), owner=user, is_archived=False).first()


class SittingForm(forms.Form):
    title = forms.CharField(label=_("Session title"), max_length=200)
    access_code = forms.CharField(
        label=_("Access code (optional)"),
        max_length=32,
        required=False,
        help_text=_("Takers must type this code to start. Leave empty for an open session."),
    )
    group = GroupChoiceField(
        label=_("Class (group)"),
        queryset=Group.objects.none(),
        required=False,
        empty_label=_("No class: students type their own name"),
        help_text=_(
            "Pick a class and students choose their name from its list; "
            "their results land on their profile automatically."
        ),
        error_messages={"invalid_choice": _("Choose one of your own classes.")},
    )
    use_pin = forms.BooleanField(
        label=_("Ask for a personal PIN"),
        required=False,
        help_text=_(
            "Students also type the PIN from their card. Students without a PIN "
            "cannot be picked in a PIN session."
        ),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Only the creator's own, non-archived classes (a foreign id fails validation).
        groups = Group.objects.none()
        if user is not None:
            groups = (
                Group.objects.filter(owner=user, is_archived=False)
                .annotate(
                    active_count=Count("students", filter=Q(students__is_active=True)),
                    no_pin_count=Count(
                        "students", filter=Q(students__is_active=True, students__pin="")
                    ),
                )
                .order_by("name")
            )
        self.fields["group"].queryset = groups

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("use_pin") and not cleaned.get("group") and "group" not in self.errors:
            self.add_error(
                "use_pin",
                _("A personal PIN needs a class. Choose a class above, or untick this box."),
            )
        return cleaned
