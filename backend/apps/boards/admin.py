from django.contrib import admin

from .models import Board, BoardColumn, Sprint


class ColumnInline(admin.TabularInline):
    model = BoardColumn
    extra = 0


@admin.register(Board)
class BoardAdmin(admin.ModelAdmin):
    list_display = ["name", "project", "kind", "deleted_at"]
    list_filter = ["kind", ("deleted_at", admin.EmptyFieldListFilter)]
    inlines = [ColumnInline]

    def get_queryset(self, request):
        # the papelera is visible here too (Board.objects hides it)
        return Board.all_objects.select_related("project")


@admin.register(Sprint)
class SprintAdmin(admin.ModelAdmin):
    list_display = ["name", "board", "state", "start_date", "end_date"]
    list_filter = ["state"]
