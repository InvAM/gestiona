"""Rule templates ("Empezar con una plantilla") built from real catalog data.

Nothing here refers to a catalog row by name. Templates that need an issue type declare a
*param*: the backend suggests a type by its semantic fields (``level`` + ``icon`` — the icon
key, not the display name, e.g. ``"bug"``), and returns two drafts:

* ``draft``          ready to save, with the suggested type already written into the JQL
                     (``null`` when no type of the project qualifies → ``ready: false``);
* ``draft_template`` the same draft with ``{{param.<key>}}`` tokens, so the UI can let the
                     user pick another type and substitute the token with
                     ``jql_value`` of the chosen type (see ``type_jql_value``).

Status ids (e.g. "done" statuses) come from the project's workflows, or from every active
status for global rules.
"""

from __future__ import annotations

import copy

from apps.issues.models import IssueType
from apps.workflows.models import Status, StatusCategory


def type_jql_value(t: IssueType) -> str:
    """How to write the type in JQL: its quoted name, or its id if the name has quotes."""
    if '"' in t.name or "\\" in t.name:
        return str(t.id)
    return f'"{t.name}"'


def _scope(project):
    if project is None:
        return list(IssueType.objects.all()), list(Status.objects.all())
    from apps.issues.services import workflow_for

    types = list(project.issue_types.all())
    status_ids: list[int] = []
    for t in types:
        for s in workflow_for(project, t).ordered_statuses():
            if s.id not in status_ids:
                status_ids.append(s.id)
    by_id = {s.id: s for s in Status.objects.filter(id__in=status_ids)}
    return types, [by_id[i] for i in status_ids if i in by_id]


def _suggest(types: list[IssueType], *, level: int, icon: str) -> IssueType | None:
    candidates = [t for t in types if t.level == level]
    return next((t for t in candidates if t.icon == icon), None)


def _token(key: str) -> str:
    return "{{param." + key + "}}"


def _fill(obj, values: dict[str, str]):
    if isinstance(obj, str):
        for k, v in values.items():
            obj = obj.replace(_token(k), v)
        return obj
    if isinstance(obj, list):
        return [_fill(x, values) for x in obj]
    if isinstance(obj, dict):
        return {k: _fill(v, values) for k, v in obj.items()}
    return obj


def _template(key: str, name: str, description: str, draft: dict,
              params: list[dict] | None = None) -> dict:
    params = params or []
    values = {p["key"]: p["jql_value"] for p in params if p.get("jql_value")}
    ready = all(p.get("value") is not None for p in params)
    return {
        "key": key, "name": name, "description": description, "params": params,
        "ready": ready,
        "draft": _fill(copy.deepcopy(draft), values) if ready else None,
        "draft_template": draft,
    }


def _type_param(key: str, label: str, types: list[IssueType], *, level: int,
                icon: str) -> dict:
    suggested = _suggest(types, level=level, icon=icon)
    return {
        "key": key, "label": label, "kind": "issue_type", "token": _token(key),
        "levels": [level],
        "options": [{"id": t.id, "name": t.name, "jql_value": type_jql_value(t)}
                    for t in types if t.level == level],
        "value": suggested.id if suggested else None,
        "jql_value": type_jql_value(suggested) if suggested else None,
    }


def build_templates(project=None) -> list[dict]:
    types, statuses = _scope(project)
    done = [s.id for s in statuses if s.category == StatusCategory.DONE]
    has_subtasks = any(t.level == IssueType.Level.SUBTASK for t in types)
    out = [
        _template(
            "assign_new_bugs", "Asignar los errores nuevos al responsable del proyecto",
            "Cuando se crea una incidencia del tipo elegido, se asigna al responsable.",
            {"name": "Asignar errores nuevos", "trigger": "issue_created",
             "conditions": [{"type": "jql", "jql": "type = {{param.issue_type}}"}],
             "actions": [{"type": "assign", "to": "lead"}]},
            [_type_param("issue_type", "Tipo de incidencia", types,
                         level=IssueType.Level.STANDARD, icon="bug")],
        ),
    ]
    if done:
        out.append(_template(
            "close_parent_when_children_done",
            "Cerrar la principal cuando todas sus subtareas estén listas",
            "Al pasar una subtarea a un estado «Listo», si todas sus hermanas también lo están,"
            " la principal pasa a ese estado.",
            {"name": "Cerrar principal al terminar subtareas", "trigger": "issue_transitioned",
             "trigger_config": {"to_status_ids": done},
             "conditions": [{"type": "children_done", "of": "parent"}],
             "actions": [{"type": "transition", "target": "parent", "status_id": done[0]}]},
        ))
    if has_subtasks:
        out.append(_template(
            "subtasks_for_new_stories", "Crear subtareas estándar para cada historia nueva",
            "Cuando se crea una incidencia del tipo elegido, se le agregan subtareas.",
            {"name": "Subtareas para historias", "trigger": "issue_created",
             "conditions": [{"type": "jql", "jql": "type = {{param.issue_type}}"}],
             "actions": [{"type": "create_subtasks",
                          "summaries": ["Diseño", "Desarrollo", "Pruebas"]}]},
            [_type_param("issue_type", "Tipo de incidencia", types,
                         level=IssueType.Level.STANDARD, icon="story")],
        ))
    out.append(_template(
        "flag_overdue", "Marcar como impedimento las incidencias vencidas (cada día 9:00)",
        "Cada mañana marca como impedimento lo vencido y sin resolver, y lo comenta.",
        {"name": "Vencidas → impedimento", "trigger": "scheduled",
         "trigger_config": {"every": "day", "time": "09:00",
                            "jql": "due < now() AND resolution = Unresolved AND flagged = false"},
         "actions": [{"type": "edit", "fields": {"flagged": True}},
                     {"type": "comment", "body": "Esta incidencia venció ({{issue.due_date}}). "
                                                 "Revisa el plan con {{issue.assignee}}."}]},
    ))
    if done:
        out.append(_template(
            "notify_reporter_on_done", "Avisar por correo al informador cuando se resuelve",
            "Envía un correo al informador cuando la incidencia llega a un estado «Listo».",
            {"name": "Avisar al informador al resolver", "trigger": "issue_transitioned",
             "trigger_config": {"to_status_ids": done},
             "actions": [{"type": "notify", "to": ["reporter"],
                          "subject": "{{issue.key}} está lista",
                          "body": "{{issue.summary}} pasó a {{issue.status}}.\n{{issue.url}}"}]},
        ))
    return out
