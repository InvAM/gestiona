from django.contrib import admin

from .models import Status, Transition, Workflow, WorkflowStatus


class WorkflowStatusInline(admin.TabularInline):
    model = WorkflowStatus
    extra = 0


class TransitionInline(admin.StackedInline):
    model = Transition
    extra = 0
    filter_horizontal = ["from_statuses", "required_roles"]


@admin.register(Workflow)
class WorkflowAdmin(admin.ModelAdmin):
    inlines = [WorkflowStatusInline, TransitionInline]


@admin.register(Status)
class StatusAdmin(admin.ModelAdmin):
    list_display = ["name", "category"]
