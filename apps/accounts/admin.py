from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class KtUserAdmin(UserAdmin):
    list_display = ("username", "display_name", "role", "is_active", "is_staff")
    list_filter = ("role", "is_active", "is_staff")
    fieldsets = (
        *UserAdmin.fieldsets,
        ("Knowledge Tester", {"fields": ("role", "display_name", "ui_language")}),
    )
