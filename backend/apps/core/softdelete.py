"""Shared API helpers for soft-deletable catalogs (DELETE → papelera, restore, purge).

Contract used by every catalog endpoint:

* ``DELETE /x/{id}``                → soft delete (204). 409 ``in_use`` when something
  active still depends on the row (e.g. a workflow used by a project).
* ``DELETE /x/{id}?permanent=true`` → hard delete, admin only. 409 ``protected`` when rows
  still reference it (``ProtectedError`` translated by the global handler).
* ``POST /x/{id}/restore``          → admin only. 409 ``name_taken`` if an active row took
  the name meanwhile.
* ``GET /x?deleted=true``           → admin only, lists the deleted rows.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from django.db import IntegrityError, transaction

from .errors import Conflict, Forbidden, NotFound


def is_system_admin(user) -> bool:
    return bool(user and user.is_authenticated and (user.is_staff or user.is_superuser))


def require_system_admin(user, message: str = "Solo los administradores pueden hacer esto"):
    if not is_system_admin(user):
        raise Forbidden(message)


def count_phrase(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def _join(parts: list[str]) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " y " + parts[-1]


def usage_message(usages: Iterable[tuple[int, str, str]]) -> str:
    """[(5, "incidencia", "incidencias"), (1, "flujo", "flujos")] →
    "No se puede borrar: lo usan 5 incidencias y 1 flujo"."""
    usages = [(n, s, p) for n, s, p in usages if n]
    total = sum(n for n, _, _ in usages)
    verb = "lo usa" if total == 1 else "lo usan"
    return f"No se puede borrar: {verb} {_join([count_phrase(n, s, p) for n, s, p in usages])}"


def usage_details(usages: Iterable[tuple[int, str, str]]) -> dict:
    return {"usages": [{"count": n, "label": p if n != 1 else s} for n, s, p in usages if n]}


def ensure_unused(*usages: tuple[int, str, str]) -> None:
    """Raise 409 when any usage count is non-zero."""
    if any(n for n, _, _ in usages):
        raise Conflict(usage_message(usages), code="in_use", details=usage_details(usages))


def protected_usages(objs: Iterable) -> list[tuple[int, str, str]]:
    """Group the objects of a ProtectedError / RestrictedError by model."""
    counter: Counter = Counter()
    names: dict = {}
    for o in objs:
        meta = o._meta
        counter[meta.label_lower] += 1
        names[meta.label_lower] = (str(meta.verbose_name), str(meta.verbose_name_plural))
    return [(n, *names[label]) for label, n in counter.most_common()]


def deleted_queryset(model, user, deleted: bool):
    """`objects` normally; the papelera (admin only) when `deleted` is true."""
    if deleted:
        require_system_admin(user, "Solo los administradores pueden ver los elementos borrados")
        return model.all_objects.deleted()
    return model.objects.all()


def get_deleted_or_404(model, pk: int, message: str = "No encontrado"):
    obj = model.all_objects.deleted().filter(pk=pk).first()
    if obj is None:
        raise NotFound(message)
    return obj


def restore(obj, conflict_message: str = "Ya existe un elemento activo con ese nombre"):
    try:
        with transaction.atomic():
            obj.restore()
    except IntegrityError as e:
        raise Conflict(conflict_message, code="name_taken") from e
    return obj


def delete(obj, user, *, permanent: bool = False) -> None:
    """Soft delete, or hard delete (admin only) when `permanent`. A hard delete of a row
    still referenced raises ProtectedError → 409 via the global handler."""
    if permanent:
        require_system_admin(user, "Solo los administradores pueden borrar definitivamente")
        with transaction.atomic():
            obj.delete()
        return
    obj.soft_delete()


def iso(d) -> str | None:
    return d.isoformat() if d else None
