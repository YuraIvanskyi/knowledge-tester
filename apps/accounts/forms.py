"""Forms of the admin area and of self-registration."""

from __future__ import annotations

from django import forms
from django.core.exceptions import ValidationError
from django.utils.crypto import constant_time_compare
from django.utils.translation import gettext_lazy as _

from . import services
from .models import SystemSettings, User

GENERATE_FIELD = "generate"  # name of the "Generate a password" submit button


def _password_field(label):
    return forms.CharField(
        label=label,
        required=False,
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )


class PasswordChoiceMixin:
    """Typed password (twice) or "Generate": validates and keeps the result in ``new_password``.

    The two fields are declared on each form as ``password1`` and ``password2``. Pressing the
    Generate button posts ``generate`` and makes the typed fields irrelevant.
    """

    new_password: str | None = None
    generated = False
    allow_generate = True

    def clean_password_choice(self, user: User) -> None:
        if self.allow_generate and GENERATE_FIELD in self.data:
            self.generated = True
            self.new_password = services.generate_password(user)
            return
        password1 = self.cleaned_data.get("password1") or ""
        password2 = self.cleaned_data.get("password2") or ""
        if not password1:
            if self.allow_generate:
                message = _("Type a password, or press the button to generate one.")
            else:
                message = _("Type a password.")
            self.add_error("password1", message)
            return
        if password1 != password2:
            self.add_error("password2", _("The two passwords do not match."))
            return
        try:
            services.validate_new_password(password1, user)
        except ValidationError as error:
            self.add_error("password1", error)
            return
        self.new_password = password1


class TeacherCreateForm(PasswordChoiceMixin, forms.ModelForm):
    password1 = _password_field(_("Password"))
    password2 = _password_field(_("Password again"))

    class Meta:
        model = User
        fields = ["username", "display_name", "role"]
        labels = {
            "username": _("Username"),
            "display_name": _("Name shown in the app"),
            "role": _("Role"),
        }
        help_texts = {
            "username": _("Used to log in. It cannot be changed later."),
            "display_name": _("For example: Olena Kovalenko."),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["display_name"].required = True
        self.fields["username"].widget.attrs.update(
            {"autocapitalize": "none", "autocomplete": "off", "autofocus": True}
        )
        self.fields["password1"].help_text = _(
            "At least 8 characters. Or leave it empty and create the account with a generated "
            "password."
        )
        self.initial.setdefault("role", User.Role.TEACHER)

    def clean_username(self):
        username = self.cleaned_data["username"]
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError(_("This username is already taken."))
        return username

    def clean_display_name(self):
        return self.cleaned_data["display_name"].strip()

    def clean(self):
        cleaned = super().clean()
        self.clean_password_choice(User(username=cleaned.get("username") or ""))
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.new_password)
        if commit:
            user.save()
        return user


class TeacherEditForm(forms.ModelForm):
    """Display name, role and active flag. The username stays as it was created."""

    class Meta:
        model = User
        fields = ["display_name", "role", "is_active"]
        labels = {
            "display_name": _("Name shown in the app"),
            "role": _("Role"),
            "is_active": _("Active (can log in)"),
        }
        help_texts = {
            "is_active": _(
                "Turn off to stop this person logging in. Nothing is deleted, and their open "
                "sessions keep working for students."
            ),
        }

    def __init__(self, *args, acting_user: User, **kwargs):
        super().__init__(*args, **kwargs)
        self.acting_user = acting_user
        self.fields["display_name"].required = True
        if self.instance.pk == acting_user.pk:
            for name in ("role", "is_active"):
                self.fields[name].disabled = True
            self.fields["role"].help_text = _(
                "You cannot change your own role or deactivate yourself."
            )
        elif self.instance.is_superuser:
            self.fields["role"].disabled = True
            self.fields["role"].help_text = _(
                "This account is a superuser, so it always has the admin role."
            )

    def clean_display_name(self):
        return self.cleaned_data["display_name"].strip()

    def clean(self):
        cleaned = super().clean()
        if "role" in cleaned and "is_active" in cleaned:
            error = services.access_change_error(
                self.instance,
                acting=self.acting_user,
                new_role=cleaned["role"],
                new_active=cleaned["is_active"],
            )
            if error:
                raise ValidationError(error)
        return cleaned


class ResetPasswordForm(PasswordChoiceMixin, forms.Form):
    """The admin types a new password or presses Generate."""

    password1 = _password_field(_("New password"))
    password2 = _password_field(_("New password again"))

    def __init__(self, *args, user: User, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["password1"].help_text = _("At least 8 characters.")

    def clean(self):
        cleaned = super().clean()
        self.clean_password_choice(self.user)
        return cleaned


class SettingsForm(forms.ModelForm):
    class Meta:
        model = SystemSettings
        fields = ["school_name", "allow_registration", "registration_code"]
        labels = {
            "school_name": _("School name"),
            "allow_registration": _("Let teachers register themselves"),
            "registration_code": _("Invite code"),
        }
        help_texts = {
            "school_name": _("Kept for later use, for example in printed sheets."),
            "allow_registration": _(
                "Off by default. When on, anyone who knows the invite code can create a "
                "teacher account at the registration page."
            ),
            "registration_code": _(
                "People must type this code to register. Share it only with colleagues."
            ),
        }

    def clean_school_name(self):
        return self.cleaned_data["school_name"].strip()

    def clean_registration_code(self):
        return self.cleaned_data["registration_code"].strip()

    def clean(self):
        cleaned = super().clean()
        code = cleaned.get("registration_code", "")
        if cleaned.get("allow_registration") and not code:
            self.add_error(
                "registration_code",
                _("Set an invite code before turning registration on. You can generate one."),
            )
        elif code and len(code) < services.MIN_INVITE_CODE_LENGTH:
            self.add_error(
                "registration_code",
                _("The invite code needs at least %(n)s characters.")
                % {"n": services.MIN_INVITE_CODE_LENGTH},
            )
        return cleaned


class RegisterForm(PasswordChoiceMixin, forms.Form):
    """Self-registration. The invite code is checked before anything else is revealed.

    ``code_wrong`` tells the view to count the failure for throttling. Username availability and
    password rules are only reported to someone who already knows the code.
    """

    allow_generate = False

    code = forms.CharField(
        label=_("Invite code"),
        strip=True,
        widget=forms.TextInput(attrs={"autocomplete": "off", "autocapitalize": "characters"}),
    )
    username = forms.CharField(
        label=_("Username"),
        max_length=User._meta.get_field("username").max_length,
        validators=User._meta.get_field("username").validators,
        help_text=_("Used to log in. It cannot be changed later."),
        widget=forms.TextInput(attrs={"autocapitalize": "none", "autocomplete": "username"}),
    )
    display_name = forms.CharField(
        label=_("Name shown in the app"),
        max_length=User._meta.get_field("display_name").max_length,
        help_text=_("For example: Olena Kovalenko."),
        widget=forms.TextInput(attrs={"autocomplete": "name"}),
    )
    password1 = _password_field(_("Password"))
    password2 = _password_field(_("Password again"))

    def __init__(self, *args, expected_code: str, **kwargs):
        super().__init__(*args, **kwargs)
        self.expected_code = expected_code
        self.code_wrong = False
        self.fields["code"].widget.attrs["autofocus"] = True
        self.fields["password1"].help_text = _("At least 8 characters.")

    def clean(self):
        cleaned = super().clean()
        code = cleaned.get("code", "")
        if not code or not constant_time_compare(code, self.expected_code):
            self.code_wrong = bool(code)
            # Report nothing else: no hint about usernames or password rules without the code.
            for name in ("username", "display_name", "password1", "password2"):
                self._errors.pop(name, None)
            if code:
                self.add_error("code", _("The invite code is not correct."))
            return cleaned
        username = cleaned.get("username")
        if username and User.objects.filter(username__iexact=username).exists():
            self.add_error("username", _("This username is already taken."))
        self.clean_password_choice(User(username=username or ""))
        return cleaned

    def clean_username(self):
        return User.normalize_username(self.cleaned_data["username"])

    def clean_display_name(self):
        return self.cleaned_data["display_name"].strip()
