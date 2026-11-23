from django.contrib import admin

from .models import Component, Project, ProjectCategory, ProjectMember, Role, Version


class MemberInline(admin.TabularInline):
    model = ProjectMember
    extra = 0
    autocomplete_fields = ["user"]


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ["key", "name", "template", "access", "lead", "is_archived"]
    list_filter = ["template", "access", "is_archived"]
    search_fields = ["key", "name"]
    inlines = [MemberInline]
    readonly_fields = ["issue_counter"]


admin.site.register(Role)
admin.site.register(ProjectCategory)
admin.site.register(Component)
admin.site.register(Version)
