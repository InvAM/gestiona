"""Compact JQL reference given to the model, built from the real parser docs plus live names
(statuses, types, priorities) so the generated query uses values that exist."""

from apps.search.jql import FIELD_DOCS, FUNCTION_DOCS


def build_reference() -> str:
    from apps.issues.models import IssueType, Priority, Resolution
    from apps.workflows.models import Status, StatusCategory

    fields = ", ".join(f"{f} ({label})" for f, label in FIELD_DOCS)
    categories = ", ".join(f'"{label}"' for _, label in StatusCategory.choices)
    return (
        "<referencia_jql>\n"
        "Sintaxis: campo OPERADOR valor; operadores = != ~ !~ > >= < <= IN (...) NOT IN (...) "
        "IS EMPTY, IS NOT EMPTY; combinadores AND, OR, NOT, paréntesis; ORDER BY campo "
        "[ASC|DESC] (también sprint, parent, labels, component, fixVersion, affectedVersion, "
        "resolution, originalEstimate, remainingEstimate, timeSpent, workRatio, flagged, "
        "votes, watchers, lastViewed, rank y campos personalizados cf[ID]; "
        "los vacíos van al final en ASC y al principio en DESC). Duraciones como 2h, "
        '"1d 4h" o minutos. Textos con espacios entre comillas dobles. '
        "~ es búsqueda de texto.\n"
        f"Campos: {fields}.\n"
        f"Funciones: {', '.join(FUNCTION_DOCS)} (las de fecha aceptan desplazamiento, "
        'p. ej. startOfWeek(-1)). Fechas relativas: "-7d", "-2w", "-1h"; absolutas: '
        '"2026-01-31".\n'
        f"statusCategory acepta: {categories}. "
        "resolution = Unresolved significa sin resolver.\n"
        f"Estados existentes: {', '.join(Status.objects.values_list('name', flat=True))}.\n"
        f"Tipos: {', '.join(IssueType.objects.values_list('name', flat=True))}.\n"
        f"Prioridades: {', '.join(Priority.objects.values_list('name', flat=True))}.\n"
        f"Resoluciones: {', '.join(Resolution.objects.values_list('name', flat=True))}.\n"
        "Ejemplos: assignee = currentUser() AND resolution = Unresolved ORDER BY priority ASC | "
        'project = WEB AND type = Error AND created >= -14d | sprint in openSprints() AND '
        'statusCategory != "Listo"\n'
        "</referencia_jql>"
    )
