"""People: class groups and the students in them (plan §14)."""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from .names import normalize_name


class Group(models.Model):
    """A class or any other set of students, owned by one teacher."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="roster_groups"
    )
    name = models.CharField(_("Name"), max_length=200)
    note = models.TextField(_("Note"), blank=True)
    is_archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["owner", "name"], name="uniq_group_name")]

    def __str__(self) -> str:
        return self.name


class Student(models.Model):
    """A person on a teacher's roster. Belongs to at most one group."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="students"
    )
    # Deleting a group never deletes its students; the service layer asks the teacher first.
    group = models.ForeignKey(
        Group, null=True, blank=True, on_delete=models.SET_NULL, related_name="students"
    )
    full_name = models.CharField(_("Full name"), max_length=200)
    # normalize_name(full_name): filled by save(), used for duplicate detection and linking.
    name_key = models.CharField(max_length=200, db_index=True, editable=False, blank=True)
    # Short code for "pick your name" entry (plan §14). Plain text on purpose: classroom
    # convenience, not a credential. Empty = no PIN.
    pin = models.CharField(_("PIN"), max_length=8, blank=True)
    notes = models.TextField(_("Notes"), blank=True)
    is_active = models.BooleanField(default=True)  # False = left the class; hidden from pickers
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["full_name"]

    def __str__(self) -> str:
        return self.full_name

    def save(self, *args, **kwargs):
        self.name_key = normalize_name(self.full_name)
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "full_name" in update_fields:
            kwargs["update_fields"] = {*update_fields, "name_key"}
        super().save(*args, **kwargs)
