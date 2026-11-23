from django.contrib import admin

from .models import CustomField, Issue, IssueLinkType, IssueType, Priority, Resolution


@admin.register(Issue)
class IssueAdmin(admin.ModelAdmin):
    list_display = ["key", "summary", "issue_type", "status", "assignee", "updated_at"]
    list_filter = ["project", "issue_type", "status"]
    search_fields = ["key", "summary"]
    raw_id_fields = ["parent", "assignee", "reporter", "sprint"]
    readonly_fields = ["key", "number", "description_text"]


for m in (IssueType, Priority, Resolution, IssueLinkType, CustomField):
    admin.site.register(m)
