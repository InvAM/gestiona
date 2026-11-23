"""Project permission resolution. Single source of truth for authorization."""

from __future__ import annotations

from django.db.models import Q, QuerySet

from apps.core.errors import Forbidden, NotFound

from .models import ALL_PERMS, Perm, Project, ProjectMember

# What a non-member gets depending on project access level.
NON_MEMBER_PERMS = {
    Project.Access.OPEN: {
        Perm.BROWSE, Perm.CREATE_ISSUES, Perm.EDIT_ISSUES, Perm.TRANSITION_ISSUES,
        Perm.ASSIGN_ISSUES, Perm.ASSIGNABLE, Perm.ADD_COMMENTS, Perm.CREATE_ATTACHMENTS,
        Perm.LINK_ISSUES, Perm.LOG_WORK,
    },
    Project.Access.LIMITED: {Perm.BROWSE, Perm.ADD_COMMENTS},
    Project.Access.PRIVATE: set(),
}


def project_perms(user, project: Project) -> set[str]:
    if not user or not user.is_authenticated or not user.is_active:
        return set()
    if user.is_superuser or project.lead_id == user.id or getattr(user, "is_bot", False):
        return set(ALL_PERMS)
    cache = getattr(user, "_gestiona_perm_cache", None)
    if cache is None:
        cache = {}
        user._gestiona_perm_cache = cache
    if project.id in cache:
        return cache[project.id]
    membership = (
        ProjectMember.objects.filter(project=project, user=user).select_related("role").first()
    )
    perms = {str(p) for p in NON_MEMBER_PERMS[project.access]}
    if membership:
        perms |= set(membership.role.permissions)
    if project.is_archived:
        perms &= {Perm.BROWSE.value, Perm.ADMINISTER.value}
    cache[project.id] = perms
    return perms


def has_perm(user, project: Project, perm: str) -> bool:
    return str(perm) in project_perms(user, project)


def require(user, project: Project, perm: str) -> None:
    perms = project_perms(user, project)
    if Perm.BROWSE.value not in perms:
        # Do not leak existence of private projects.
        raise NotFound("Proyecto no encontrado")
    if str(perm) not in perms:
        raise Forbidden("No tienes permiso para realizar esta acción")


def visible_projects(user) -> QuerySet[Project]:
    qs = Project.objects.all()
    if user.is_superuser:
        return qs
    return qs.filter(
        Q(access__in=[Project.Access.OPEN, Project.Access.LIMITED])
        | Q(memberships__user=user)
        | Q(lead=user)
    ).distinct()


def assignable_users(project: Project):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    users = User.objects.filter(is_active=True, is_bot=False)
    if project.access == Project.Access.OPEN:
        return users
    member_ids = ProjectMember.objects.filter(
        project=project, role__permissions__contains=[Perm.ASSIGNABLE.value]
    ).values("user_id")
    return users.filter(Q(id__in=member_ids) | Q(id=project.lead_id) | Q(is_superuser=True))
