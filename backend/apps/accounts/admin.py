from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ["email"]
    list_display = ["email", "full_name", "is_active", "is_staff", "last_login"]
    list_filter = ["is_active", "is_staff", "is_superuser"]
    search_fields = ["email", "full_name"]
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Perfil", {"fields": ("full_name", "job_title", "avatar", "timezone", "locale")}),
        ("Permisos", {"fields": ("is_active", "is_staff", "is_superuser", "groups")}),
        ("Fechas", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",),
                             "fields": ("email", "full_name", "password1", "password2")}),)
