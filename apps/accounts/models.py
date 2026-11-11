from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        TEACHER = "teacher", "Teacher"

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
