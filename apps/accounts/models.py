from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin", _("Admin")
        TEACHER = "teacher", _("Teacher")

    role = models.CharField(max_length=10, choices=Role.choices, default=Role.TEACHER)
    display_name = models.CharField(max_length=150, blank=True)
    ui_language = models.CharField(max_length=8, blank=True)

    def save(self, *args, **kwargs):
        if self.is_superuser:
            self.role = self.Role.ADMIN
        super().save(*args, **kwargs)

    @property
    def is_admin_role(self) -> bool:
        return self.role == self.Role.ADMIN

    def __str__(self) -> str:
        return self.display_name or self.get_username()


class SystemSettings(models.Model):
    """Site-wide settings edited by an admin in /manage/. A single row (pk=1): use `load()`."""

    school_name = models.CharField(max_length=200, blank=True)
    # Self-registration of teachers (plan §14): off by default, needs the invite code when on.
    allow_registration = models.BooleanField(default=False)
    registration_code = models.CharField(max_length=64, blank=True)

    class Meta:
        verbose_name_plural = "system settings"

    def __str__(self) -> str:
        return "System settings"

    @classmethod
    def load(cls) -> "SystemSettings":
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj
