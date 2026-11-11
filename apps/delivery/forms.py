from django import forms
from django.utils.translation import gettext_lazy as _


class SittingForm(forms.Form):
    title = forms.CharField(label=_("Session title"), max_length=200)
    access_code = forms.CharField(
        label=_("Access code (optional)"),
        max_length=32,
        required=False,
        help_text=_("Takers must type this code to start. Leave empty for an open session."),
    )
