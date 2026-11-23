from django.db import models
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SoftDeleteQuerySet(models.QuerySet):
    def alive(self):
        return self.filter(deleted_at__isnull=True)

    def deleted(self):
        return self.filter(deleted_at__isnull=False)


class SoftDeleteManager(models.Manager.from_queryset(SoftDeleteQuerySet)):
    """Default manager: hides soft-deleted rows."""

    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class AllObjectsManager(models.Manager.from_queryset(SoftDeleteQuerySet)):
    """Every row, deleted or not (`.alive()` / `.deleted()` to narrow)."""


class SoftDeleteModel(models.Model):
    """Catalog / configuration rows are never hard-deleted from the API.

    * ``Model.objects`` hides deleted rows (selectors, JQL values, project metadata…).
    * ``Model.all_objects`` includes them (admin "papelera", restore).
    * Forward FK access (``issue.priority``) goes through Django's ``_base_manager``, a plain
      manager, so issues that already point at a deleted row keep showing it.
    * Unique names must be declared as ``UniqueConstraint(..., condition=ALIVE)`` so a
      deleted name can be reused.
    """

    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True, editable=False)

    objects = SoftDeleteManager()
    all_objects = AllObjectsManager()

    class Meta:
        abstract = True

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def soft_delete(self, *, save: bool = True) -> None:
        if self.deleted_at is None:
            self.deleted_at = timezone.now()
            if save:
                self.save(update_fields=self._soft_delete_update_fields())

    def restore(self, *, save: bool = True) -> None:
        """Undelete. Raises IntegrityError if an active row already took the name."""
        if self.deleted_at is not None:
            self.deleted_at = None
            if save:
                self.save(update_fields=self._soft_delete_update_fields())

    def _soft_delete_update_fields(self) -> list[str]:
        fields = ["deleted_at"]
        if any(f.name == "updated_at" for f in self._meta.concrete_fields):
            fields.append("updated_at")
        return fields


# Condition for "unique among non-deleted rows" constraints.
ALIVE = models.Q(deleted_at__isnull=True)
