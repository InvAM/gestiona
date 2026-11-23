"""JQL-compatible query language → Django Q objects.

Supported:
  field = value | != | ~ | !~ | > | >= | < | <= | IN (..) | NOT IN (..) | IS [NOT] EMPTY
  AND / OR / NOT / parentheses, ORDER BY field [ASC|DESC], ...
  functions: currentUser(), openSprints(), closedSprints(), futureSprints(), now(),
             startOfDay/Week/Month/Year([offset]), endOfDay/Week/Month/Year([offset]),
             unreleasedVersions(), releasedVersions()
  relative dates: "-7d", "2w", "-1h", "30m"; absolute: "2026-01-31" or "2026-01-31 14:00"

ORDER BY (Jira semantics; EMPTY sorts after every value: last in ASC, first in DESC; the
search always breaks ties by id):
  key                 project key, then number (DEMO-2 before DEMO-10)
  sprint              current sprint's start date, then sprint id
  parent / principal  parent's key, naturally (project key, then number)
  labels              first label alphabetically, case-insensitive
  cf[ID] / name       by the field kind: number, date, datetime, text (case-insensitive),
                      select (option position), multiselect/checkbox (first option by
                      position), labels (first label), user/multiuser (display name)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.search import SearchQuery
from django.db.models import (
    DateField,
    DateTimeField,
    Exists,
    Expression,
    F,
    FloatField,
    IntegerField,
    OuterRef,
    Q,
    Subquery,
    TextField,
    Value,
)
from django.db.models.functions import NullIf
from django.db.models.lookups import (
    Exact,
    GreaterThan,
    GreaterThanOrEqual,
    LessThan,
    LessThanOrEqual,
)
from django.utils import timezone
from lark import Lark, Token, Transformer, v_args
from lark.exceptions import LarkError, UnexpectedInput

GRAMMAR = r"""
?start: query
query: or_expr? order_by?

?or_expr: and_expr (_OR and_expr)*
?and_expr: not_expr (_AND not_expr)*
?not_expr: _NOT not_expr -> negate
         | "(" or_expr ")"
         | clause

clause: field OP value                 -> compare
      | field _IN list                 -> in_list
      | field _NOT _IN list            -> not_in_list
      | field _IS _EMPTYKW             -> is_empty
      | field _IS _NOT _EMPTYKW        -> is_not_empty

field: NAME | STRING | CF
list: "(" [value ("," value)*] ")"
     | function
?value: STRING          -> string
      | NUMBER          -> number
      | NAME            -> word
      | function
      | _EMPTYKW        -> empty
function: NAME "(" [value ("," value)*] ")"

order_by: _ORDER _BY order_item ("," order_item)*
order_item: field DIRECTION?

OP: "!=" | ">=" | "<=" | "!~" | "=" | "~" | ">" | "<"
DIRECTION.2: /(asc|desc)\b/i
_OR.2: /or\b/i
_AND.2: /and\b/i
_NOT.2: /not\b/i
_IN.2: /in\b/i
_IS.2: /is\b/i
_ORDER.2: /order\b/i
_BY.2: /by\b/i
_EMPTYKW.2: /empty\b/i | /null\b/i
CF.3: /cf\[\d+\]/i
NAME: /[\w\-\.@+:\/]+/
STRING: /"(?:[^"\\]|\\.)*"/ | /'(?:[^'\\]|\\.)*'/
NUMBER.3: /-?\d+(\.\d+)?(?![A-Za-z0-9_\-])/

%import common.WS
%ignore WS
"""

_parser = Lark(GRAMMAR, parser="lalr", maybe_placeholders=False)


class JQLError(ValueError):
    def __init__(self, message: str, position: int | None = None):
        super().__init__(message)
        self.message = message
        self.position = position


@dataclass
class Func:
    name: str
    args: list


@dataclass
class Empty:
    pass


@dataclass
class Clause:
    field: str
    op: str
    value: object


@dataclass
class Node:
    kind: str  # and | or | not
    children: list = field(default_factory=list)


@dataclass
class ParsedQuery:
    where: object | None
    order: list[tuple[str, bool]]  # (field, descending)


def _unquote(s: str) -> str:
    body = s[1:-1]
    return re.sub(r"\\(.)", r"\1", body)


@v_args(inline=True)
class _ToAst(Transformer):
    def query(self, *parts):
        where, order = None, []
        for p in parts:
            if isinstance(p, list):
                order = p
            else:
                where = p
        return ParsedQuery(where, order)

    def or_expr(self, *items):
        return Node("or", list(items))

    def and_expr(self, *items):
        return Node("and", list(items))

    def negate(self, item):
        return Node("not", [item])

    def field(self, tok):
        s = str(tok)
        if tok.type == "STRING":
            s = _unquote(s)
        return s

    def compare(self, f, op, value):
        return Clause(f, str(op), value)

    def in_list(self, f, values):
        return Clause(f, "in", values)

    def not_in_list(self, f, values):
        return Clause(f, "not in", values)

    def is_empty(self, f):
        return Clause(f, "is", Empty())

    def is_not_empty(self, f):
        return Clause(f, "is not", Empty())

    def list(self, *values):
        if len(values) == 1 and isinstance(values[0], Func):
            return values[0]
        return [v for v in values if v is not None]

    def string(self, tok):
        return _unquote(str(tok))

    def number(self, tok):
        return str(tok)

    def word(self, tok):
        return str(tok)

    def empty(self, *_):
        return Empty()

    def function(self, name, *args):
        return Func(str(name).lower(), [a for a in args if a is not None])

    def order_by(self, *items):
        return list(items)

    def order_item(self, f, direction: Token | None = None):
        return (f, bool(direction and str(direction).lower() == "desc"))


def parse(jql: str) -> ParsedQuery:
    jql = (jql or "").strip()
    if not jql:
        return ParsedQuery(None, [])
    try:
        tree = _parser.parse(jql)
    except UnexpectedInput as e:
        pos = getattr(e, "pos_in_stream", None)
        near = jql[pos:pos + 20] if pos is not None else ""
        raise JQLError(f"Error de sintaxis cerca de «{near}»" if near else
                       "Consulta incompleta", pos) from e
    except LarkError as e:
        raise JQLError("Consulta inválida") from e
    result = _ToAst().transform(tree)
    if isinstance(result, ParsedQuery):
        return result
    return ParsedQuery(result, [])


# --------------------------------------------------------------------------- compiler

FIELD_ALIASES = {
    "project": "project", "proyecto": "project",
    "key": "key", "issue": "key", "issuekey": "key", "clave": "key",
    "id": "id",
    "summary": "summary", "resumen": "summary",
    "description": "description", "descripcion": "description", "descripción": "description",
    "text": "text", "texto": "text",
    "comment": "comment", "comentario": "comment",
    "type": "type", "issuetype": "type", "tipo": "type",
    "status": "status", "estado": "status",
    "statuscategory": "statuscategory", "categoria": "statuscategory",
    "priority": "priority", "prioridad": "priority",
    "resolution": "resolution", "resolucion": "resolution", "resolución": "resolution",
    "assignee": "assignee", "responsable": "assignee", "asignado": "assignee",
    "reporter": "reporter", "informador": "reporter",
    "labels": "labels", "label": "labels", "etiquetas": "labels", "etiqueta": "labels",
    "component": "component", "components": "component", "componente": "component",
    "componentes": "component",
    "fixversion": "fixversion", "fixversions": "fixversion", "version": "fixversion",
    "versión": "fixversion", "versión de corrección": "fixversion",
    "version de correccion": "fixversion",
    "affectedversion": "affectedversion", "affectsversion": "affectedversion",
    "affectedversions": "affectedversion", "versión afectada": "affectedversion",
    "version afectada": "affectedversion",
    "originalestimate": "originalestimate", "timeoriginalestimate": "originalestimate",
    "estimación original": "originalestimate", "estimacion original": "originalestimate",
    "estimacionoriginal": "originalestimate",
    "remainingestimate": "remainingestimate", "timeestimate": "remainingestimate",
    "estimación restante": "remainingestimate", "estimacion restante": "remainingestimate",
    "estimacionrestante": "remainingestimate",
    "timespent": "timespent", "tiempo registrado": "timespent",
    "tiemporegistrado": "timespent",
    "workratio": "workratio", "ratio de trabajo": "workratio", "ratiotrabajo": "workratio",
    "votes": "votes", "votos": "votes",
    "lastviewed": "lastviewed", "última visita": "lastviewed", "ultima visita": "lastviewed",
    "ultimavisita": "lastviewed",
    "sprint": "sprint",
    "parent": "parent", "epic": "parent", "\"epic link\"": "parent", "epic link": "parent",
    "principal": "parent",
    "created": "created", "createddate": "created", "creado": "created",
    "updated": "updated", "updateddate": "updated", "actualizado": "updated",
    "resolved": "resolved", "resolutiondate": "resolved", "resuelto": "resolved",
    "due": "due", "duedate": "due", "vencimiento": "due",
    "startdate": "startdate", "inicio": "startdate",
    "story points": "storypoints", "storypoints": "storypoints", "puntos": "storypoints",
    "watcher": "watcher", "watchers": "watcher", "observador": "watcher",
    "voter": "voter",
    "flagged": "flagged", "marcada": "flagged",
    "team": "team", "equipo": "team",
}

ORDERABLE = {
    "key": "number", "id": "id", "summary": "summary", "created": "created_at",
    "updated": "updated_at", "resolved": "resolved_at", "due": "due_date",
    "startdate": "start_date", "priority": "priority__position", "status": "status__name",
    "assignee": "assignee__full_name", "reporter": "reporter__full_name",
    "type": "issue_type__position", "storypoints": "story_points", "rank": "rank",
    "project": "project__key", "statuscategory": "status__category", "team": "team__name",
    "originalestimate": "original_estimate", "remainingestimate": "remaining_estimate",
}
# Sortable fields whose ORDER BY is not a plain column (see `_Compiler.order_terms`).
ORDERABLE_EXPR = ("sprint", "parent", "labels", "component", "fixversion", "affectedversion",
                  "resolution", "timespent", "workratio", "flagged", "votes", "voter",
                  "watcher", "lastviewed")
# Time tracking fields (seconds in the model; JQL values like "2h", "1d 4h" or minutes).
DURATION_FIELDS = {"originalestimate": "original_estimate",
                   "remainingestimate": "remaining_estimate", "timespent": "time_spent"}
_DURATION_UNITS = {"w": 5 * 8 * 3600, "d": 8 * 3600, "h": 3600, "m": 60}  # Jira: 1d = 8h
_DURATION_RE = re.compile(r"(?:\s*\d+(?:\.\d+)?\s*[wdhm])+\s*", re.I)

_CF_RE = re.compile(r"cf\[(\d+)\]")


def is_orderable(name: str) -> bool:
    """`name` is canonical: a FIELD_ALIASES value, "rank" or "cf[ID]"."""
    return name in ORDERABLE or name in ORDERABLE_EXPR or bool(_CF_RE.fullmatch(name))


def doc_is_orderable(doc_name: str) -> bool:
    """For the names of FIELD_DOCS / SORT_ONLY_DOCS (as the JQL editor offers them)."""
    low = doc_name.strip().strip('"').lower()
    return is_orderable(FIELD_ALIASES.get(low, low))


FIELD_DOCS = [
    ("project", "Proyecto"), ("key", "Clave"), ("summary", "Resumen"),
    ("description", "Descripción"), ("text", "Texto (resumen, descripción, comentarios)"),
    ("comment", "Comentario"), ("type", "Tipo"), ("status", "Estado"),
    ("statusCategory", "Categoría de estado"), ("priority", "Prioridad"),
    ("resolution", "Resolución"), ("assignee", "Responsable"), ("reporter", "Informador"),
    ("labels", "Etiquetas"), ("component", "Componente"), ("fixVersion", "Versión"),
    ("affectedVersion", "Versión afectada"), ("sprint", "Sprint"), ("parent", "Principal"),
    ("created", "Creado"), ("updated", "Actualizado"), ("resolved", "Resuelto"),
    ("due", "Vencimiento"), ("startDate", "Fecha de inicio"),
    ("\"story points\"", "Puntos de historia"), ("watcher", "Observador"),
    ("flagged", "Marcada"), ("team", "Equipo"),
    ("originalEstimate", "Estimación original"), ("remainingEstimate", "Estimación restante"),
    ("timeSpent", "Tiempo registrado"), ("workRatio", "Ratio de trabajo (%)"),
    ("votes", "Votos"), ("lastViewed", "Última visita"),
]
# Only valid after ORDER BY.
SORT_ONLY_DOCS = [("rank", "Rango")]

FUNCTION_DOCS = [
    "currentUser()", "openSprints()", "closedSprints()", "futureSprints()", "now()",
    "startOfDay()", "endOfDay()", "startOfWeek()", "endOfWeek()", "startOfMonth()",
    "endOfMonth()", "startOfYear()", "endOfYear()", "unreleasedVersions()",
    "releasedVersions()",
]

STATUS_CATEGORY_ALIASES = {
    "to do": "todo", "todo": "todo", "por hacer": "todo", "new": "todo",
    "in progress": "in_progress", "in_progress": "in_progress", "en curso": "in_progress",
    "indeterminate": "in_progress",
    "done": "done", "listo": "done", "complete": "done",
}

_REL_RE = re.compile(r"^([+-]?)(\d+)([wdhm])$", re.I)


@dataclass
class CompiledQuery:
    q: Q
    order_by: list


# --------------------------------------------------------------------------- ORDER BY SQL

_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")


class _SqlTemplate(Expression):
    """Fixed SQL over named source expressions: every «{name}» becomes the compiled source
    (its params appended in order), so a column can be referenced several times. Used for
    sort keys Django cannot express (unnest, jsonb arrays, safe casts). Templates must not
    contain «%» (they reach the driver as-is)."""

    def __init__(self, template: str, output_field, **sources):
        super().__init__(output_field=output_field)
        self.template = template
        self.names = list(sources)
        self.sources = list(sources.values())

    def get_source_expressions(self):
        return self.sources

    def set_source_expressions(self, exprs):
        self.sources = list(exprs)

    def as_sql(self, compiler, connection):
        by_name = dict(zip(self.names, self.sources, strict=True))
        params: list = []

        def sub(m):
            sql, p = compiler.compile(by_name[m.group(1)])
            params.extend(p)
            return sql

        return _PLACEHOLDER.sub(sub, self.template), params

    def get_group_by_cols(self):
        # Only the issue's own columns: functionally dependent on its pk when grouped.
        cols = []
        for s in self.sources:
            cols.extend(s.get_group_by_cols())
        return cols


# System labels: first label alphabetically, case-insensitive (no labels → NULL).
_LABELS_SQL = "(SELECT min(NULLIF(lower(jql_l.v), '')) FROM unnest({labels}) AS jql_l(v))"
# Custom-field value (@K = quoted key). Values that do not fit the field kind (e.g. a field
# whose kind changed) sort as EMPTY instead of failing the query: pg_input_is_valid (PG 16+).
_CF_TEXT = "(CASE WHEN jsonb_typeof({cf} -> @K) IN ('string', 'number') THEN {cf} ->> @K END)"
_CF_ARRAY = ("jsonb_array_elements_text(CASE WHEN jsonb_typeof({cf} -> @K) = 'array' "
             "THEN {cf} -> @K END)")
_USER_NAME = "lower(COALESCE(NULLIF(jql_u.full_name, ''), split_part(jql_u.email, '@', 1)))"
# User ids: an immutable guard (a regex, not pg_input_is_valid) keeps «id = …» an index
# lookup on the users table instead of a scan per issue.
_ID_RE = "'^[0-9]{1,18}$'"
_CF_USER_ID = f"(CASE WHEN ({{cf}} ->> @K) ~ {_ID_RE} THEN ({{cf}} ->> @K)::bigint END)"


def _cf_cast(sql_type: str) -> str:
    return (f"(CASE WHEN pg_input_is_valid({{cf}} ->> @K, '{sql_type}') "
            f"THEN ({{cf}} ->> @K)::{sql_type} END)")


def _custom_field_sort(cf) -> Expression:
    """Sort key of a custom field according to its kind (see the module docstring)."""
    kind = cf.kind
    opts = Value([str(o.get("id")) for o in cf.options or []],
                 output_field=ArrayField(TextField()))
    users = '"' + get_user_model()._meta.db_table + '"'
    if kind == "number":
        sql, out = _cf_cast("double precision"), FloatField()
    elif kind == "date":
        sql, out = _cf_cast("date"), DateField()
    elif kind == "datetime":
        sql, out = _cf_cast("timestamptz"), DateTimeField()
    elif kind == "select":
        sql, out = f"array_position({{opts}}::text[], {_CF_TEXT})", IntegerField()
    elif kind in ("multiselect", "checkbox"):
        sql = (f"(SELECT min(array_position({{opts}}::text[], jql_e.v)) "
               f"FROM {_CF_ARRAY} AS jql_e(v))")
        out = IntegerField()
    elif kind == "labels":
        sql = f"(SELECT min(NULLIF(lower(jql_e.v), '')) FROM {_CF_ARRAY} AS jql_e(v))"
        out = TextField()
    elif kind == "user":
        sql = f"(SELECT {_USER_NAME} FROM {users} AS jql_u WHERE jql_u.id = {_CF_USER_ID})"
        out = TextField()
    elif kind == "multiuser":
        sql = (f"(SELECT min({_USER_NAME}) FROM {users} AS jql_u WHERE jql_u.id IN "
               f"(SELECT CASE WHEN jql_e.v ~ {_ID_RE} THEN jql_e.v::bigint END "
               f"FROM {_CF_ARRAY} AS jql_e(v)))")
        out = TextField()
    else:  # text, textarea, url (and any future scalar kind)
        sql, out = f"NULLIF(lower(btrim({_CF_TEXT})), '')", TextField()
    sql = sql.replace("@K", f"'{int(cf.id)}'")
    sources = {"cf": F("custom_fields")}
    if "{opts}" in sql:
        sources["opts"] = opts
    return _SqlTemplate(sql, out, **sources)


def _q(name: str) -> str:
    return f'"{name}"'


def _m2m(field_name: str) -> tuple[str, str, str]:
    """(through table, column to the issue, column to the target) of an Issue M2M."""
    from apps.issues.models import Issue

    f = Issue._meta.get_field(field_name)
    return (_q(f.remote_field.through._meta.db_table), _q(f.m2m_column_name()),
            _q(f.m2m_reverse_name()))


def _components_sort() -> Expression:
    """First component by name, case-insensitive (deleted components still count: the
    issue keeps showing them)."""
    from apps.projects.models import Component

    table, col, target = _m2m("components")
    # nested pk lookups, not a JOIN: the planner would hash-join once per issue (~4x slower)
    return _SqlTemplate(
        f"(SELECT min((SELECT lower(jql_c.name) FROM {_q(Component._meta.db_table)} AS jql_c "
        f"WHERE jql_c.id = jql_m.{target})) FROM {table} AS jql_m "
        f"WHERE jql_m.{col} = {{pk}})", TextField(), pk=F("pk"))


def _versions_sort(field_name: str) -> Expression:
    """Version sequence like Jira: the project's version order (`Version.position`, the
    order of the project's version list, then id), the lowest of the issue's versions.
    Versions of different projects go by project key. One text key, compared bytewise."""
    from apps.projects.models import Project, Version

    table, col, target = _m2m(field_name)
    return _SqlTemplate(
        f"(SELECT min((SELECT (jql_p.key || chr(1) || lpad(jql_v.position::text, 10, '0') || "
        f"lpad(jql_v.id::text, 20, '0')) COLLATE \"C\" "
        f"FROM {_q(Version._meta.db_table)} AS jql_v "
        f"JOIN {_q(Project._meta.db_table)} AS jql_p ON jql_p.id = jql_v.project_id "
        f"WHERE jql_v.id = jql_m.{target})) FROM {table} AS jql_m "
        f"WHERE jql_m.{col} = {{pk}})", TextField(), pk=F("pk"))


def _count_of(field_name: str) -> Expression:
    """Number of voters / watchers (0 is a value, not EMPTY, as in Jira)."""
    table, col, _ = _m2m(field_name)
    return _SqlTemplate(f"(SELECT count(*) FROM {table} AS jql_m WHERE jql_m.{col} = {{pk}})",
                        IntegerField(), pk=F("pk"))


def _work_ratio() -> Expression:
    """Jira's workRatio: time spent / original estimate × 100 (EMPTY without estimate)."""
    return _SqlTemplate("(CASE WHEN {oe} > 0 THEN {ts} * 100.0 / {oe} END)", FloatField(),
                        oe=F("original_estimate"), ts=F("time_spent"))


class _Compiler:
    def __init__(self, user, project=None):
        self.user = user
        self.project = project
        self.User = get_user_model()
        self._visible = None
        self._custom_fields: dict = {}  # id → CustomField | None (one query per field)

    @property
    def visible(self):
        """Projects the requesting user may see. Every name lookup is scoped to this so
        the query language cannot be used as an existence oracle for private data."""
        if self._visible is None:
            from apps.projects.models import Project
            from apps.projects.permissions import visible_projects

            self._visible = visible_projects(self.user) if self.user else Project.objects.all()
        return self._visible

    # ----- tree
    def compile(self, node) -> Q:
        if node is None:
            return Q()
        if isinstance(node, Node):
            if node.kind == "not":
                return ~self.compile(node.children[0])
            parts = [self.compile(c) for c in node.children]
            q = parts[0]
            for p in parts[1:]:
                q = (q & p) if node.kind == "and" else (q | p)
            return q
        return self.clause(node)

    def field_name(self, raw: str) -> str:
        low = raw.strip().lower()
        if re.fullmatch(r"cf\[\d+\]", low):
            return low
        if low in FIELD_ALIASES:
            return FIELD_ALIASES[low]
        from apps.issues.models import CustomField

        cf = CustomField.objects.filter(name__iexact=raw.strip()).first()
        if cf:
            self._custom_fields[cf.id] = cf
            return f"cf[{cf.id}]"
        raise JQLError(f"El campo «{raw}» no existe")

    def recent_views(self):
        """The requesting user's view of each issue (one row at most: unique constraint)."""
        from apps.search.models import RecentItem

        return RecentItem.objects.filter(user_id=getattr(self.user, "id", None), kind="issue",
                                         object_id=OuterRef("pk"))

    def last_viewed(self) -> Expression:
        """When the requesting user last opened the issue (EMPTY = never)."""
        return Subquery(self.recent_views().values("viewed_at")[:1],
                        output_field=DateTimeField())

    def parse_duration(self, v) -> int:
        """Seconds of a Jira duration: "2h", "1d 4h", "1w" (1d = 8h, 1w = 5d) or a plain
        number of minutes."""
        s = str(v).strip().lower()
        if re.fullmatch(r"\d+(\.\d+)?", s):
            return int(Decimal(s) * 60)
        if not _DURATION_RE.fullmatch(s):
            raise JQLError(f"Duración inválida: «{v}» (usa p. ej. 2h, 1d 4h o minutos)")
        return int(sum(Decimal(n) * _DURATION_UNITS[u]
                       for n, u in re.findall(r"(\d+(?:\.\d+)?)\s*([wdhm])", s)))

    def custom_field(self, cid: int):
        """Deleted fields still sort (their values stay on the issues)."""
        if cid not in self._custom_fields:
            from apps.issues.models import CustomField

            self._custom_fields[cid] = CustomField.all_objects.filter(pk=cid).first()
        return self._custom_fields[cid]

    # ----- values
    def _func_values(self, fn: Func, fname: str):
        from apps.boards.models import Sprint
        from apps.projects.models import Version

        n = fn.name
        if n == "currentuser":
            return [self.user]
        if n in ("opensprints", "closedsprints", "futuresprints"):
            state = {"opensprints": "active", "closedsprints": "closed",
                     "futuresprints": "future"}[n]
            return list(Sprint.objects.filter(state=state, board__project__in=self.visible))
        if n in ("unreleasedversions", "releasedversions"):
            st = "unreleased" if n == "unreleasedversions" else "released"
            qs = Version.objects.filter(status=st, project__in=self.visible)
            if fn.args:
                qs = qs.filter(project__key__iexact=str(fn.args[0]))
            return list(qs)
        if n == "now" or n.startswith("startof") or n.startswith("endof"):
            return [self._date_function(fn)]
        raise JQLError(f"Función desconocida: {fn.name}()")

    def _date_function(self, fn: Func) -> datetime:
        now = timezone.localtime()
        if fn.name == "now":
            return now
        offset = timedelta()
        unit_map = {"d": "days", "w": "weeks", "h": "hours", "m": "minutes"}
        if fn.args:
            m = _REL_RE.match(str(fn.args[0]))
            if not m:
                raise JQLError(f"Desplazamiento inválido en {fn.name}()")
            sign = -1 if m.group(1) == "-" else 1
            offset = timedelta(**{unit_map[m.group(3).lower()]: sign * int(m.group(2))})
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        kind = fn.name[7:] if fn.name.startswith("startof") else fn.name[5:]
        if kind == "day":
            start = start_of_day
            end = start + timedelta(days=1)
        elif kind == "week":
            start = start_of_day - timedelta(days=start_of_day.weekday())
            end = start + timedelta(weeks=1)
        elif kind == "month":
            start = start_of_day.replace(day=1)
            end = (start + timedelta(days=32)).replace(day=1)
        elif kind == "year":
            start = start_of_day.replace(month=1, day=1)
            end = start.replace(year=start.year + 1)
        else:
            raise JQLError(f"Función desconocida: {fn.name}()")
        base = start if fn.name.startswith("startof") else end - timedelta(microseconds=1)
        return base + offset

    def values(self, raw, fname: str) -> list:
        items = raw if isinstance(raw, list) else [raw]
        out = []
        for item in items:
            if isinstance(item, Func):
                out.extend(self._func_values(item, fname))
            else:
                out.append(item)
        return out

    def parse_date(self, v) -> datetime:
        if isinstance(v, datetime):
            return v
        s = str(v).strip()
        m = _REL_RE.match(s)
        if m:
            sign = -1 if m.group(1) == "-" else 1
            unit = {"d": "days", "w": "weeks", "h": "hours", "m": "minutes"}[m.group(3).lower()]
            return timezone.now() + timedelta(**{unit: sign * int(m.group(2))})
        for fmt in ("%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M", "%Y-%m-%d", "%Y/%m/%d"):
            try:
                dt = datetime.strptime(s, fmt)
                return timezone.make_aware(dt) if timezone.is_naive(dt) else dt
            except ValueError:
                continue
        raise JQLError(f"Fecha inválida: «{s}»")

    def resolve_users(self, vals) -> list[int]:
        ids = []
        for v in vals:
            if isinstance(v, self.User):
                ids.append(v.id)
                continue
            s = str(v)
            if s.isdigit():
                ids.append(int(s))
                continue
            u = self.User.objects.filter(
                Q(email__iexact=s) | Q(full_name__iexact=s) | Q(email__istartswith=s + "@")
            ).first()
            if u is None:
                raise JQLError(f"El usuario «{s}» no existe")
            ids.append(u.id)
        return ids

    def resolve_named(self, model, vals, label: str, extra: Q | None = None) -> list[int]:
        ids = []
        for v in vals:
            if hasattr(v, "pk"):
                ids.append(v.pk)
                continue
            s = str(v)
            qs = model.objects.all()
            if extra is not None:
                qs = qs.filter(extra)
            obj = qs.filter(pk=int(s)).first() if s.isdigit() else None
            if obj is None:
                obj = qs.filter(name__iexact=s).first()
            if obj is None:
                raise JQLError(f"El valor «{s}» no existe para {label} o no tienes acceso")
            ids.append(obj.pk)
        return ids

    # ----- clause
    def clause(self, c: Clause) -> Q:
        from apps.boards.models import Sprint
        from apps.issues.models import Comment, Issue, IssueType, Priority, Resolution
        from apps.projects.models import Component, Version
        from apps.workflows.models import Status

        f = self.field_name(c.field)
        op = c.op.lower()
        empty = isinstance(c.value, Empty) or (
            not isinstance(c.value, list) and isinstance(c.value, Empty)
        )

        def eq_neg(q_pos: Q) -> Q:
            if op in ("=", "in"):
                return q_pos
            if op in ("!=", "not in"):
                return ~q_pos
            raise JQLError(f"El operador «{c.op}» no aplica al campo {c.field}")

        def null_check(path: str) -> Q:
            if op == "is" or (op == "=" and empty):
                return Q(**{f"{path}__isnull": True})
            if op == "is not" or (op == "!=" and empty):
                return Q(**{f"{path}__isnull": False})
            raise JQLError("Operador inválido para EMPTY")

        # text fields
        if f in ("summary", "description", "comment", "text"):
            if op in ("is", "is not"):
                path = {"summary": "summary", "description": "description_text"}.get(f)
                if not path:
                    raise JQLError("EMPTY no aplica a este campo")
                q = Q(**{path: ""}) | Q(**{f"{path}__isnull": True})
                return q if op == "is" else ~q
            if op not in ("~", "!~"):
                raise JQLError(f"Usa ~ o !~ para buscar texto en {c.field}")
            term = str(self.values(c.value, f)[0]).strip()
            if not term:
                raise JQLError("Texto de búsqueda vacío")
            if f == "summary":
                q = Q(summary__icontains=term)
            elif f == "description":
                q = Q(description_text__icontains=term)
            elif f == "comment":
                q = Q(Exists(Comment.objects.filter(issue=OuterRef("pk"),
                                                    body_text__icontains=term)))
            else:
                words = re.findall(r"[\w\-]+", term)
                if not words:
                    raise JQLError("Texto de búsqueda vacío")
                tsq = " & ".join(f"{w}:*" for w in words)
                q = Q(search_vector=SearchQuery(tsq, search_type="raw", config="simple")) | \
                    Q(summary__icontains=term)
            return q if op == "~" else ~q

        if op in ("is", "is not") or empty:
            paths = {
                "assignee": "assignee", "reporter": "reporter", "resolution": "resolution",
                "parent": "parent", "sprint": "sprint", "due": "due_date",
                "startdate": "start_date", "resolved": "resolved_at",
                "storypoints": "story_points", "component": "components",
                "fixversion": "fix_versions", "affectedversion": "affects_versions",
                "team": "team", "originalestimate": "original_estimate",
                "remainingestimate": "remaining_estimate",
            }
            # EMPTY of fields that are not a nullable column
            special = {
                "labels": lambda: Q(labels=[]),
                "timespent": lambda: Q(time_spent=0),
                "workratio": lambda: Q(original_estimate__isnull=True) | Q(original_estimate=0),
                "lastviewed": lambda: ~Q(Exists(self.recent_views())),
            }
            if f in special:
                q = special[f]()
                return q if (op == "is" or op == "=") else ~q
            if f.startswith("cf["):
                cid = f[3:-1]
                q = Q(**{f"custom_fields__{cid}__isnull": True})
                return q if (op == "is" or op == "=") else ~q
            if f not in paths:
                raise JQLError(f"El campo {c.field} no admite EMPTY")
            return null_check(paths[f])

        vals = self.values(c.value, f)
        if not vals and op in ("in", "not in"):
            return Q(pk__in=[]) if op == "in" else Q()

        if f == "project":
            ids = []
            for v in vals:
                s = str(v)
                p = self.visible.filter(Q(key__iexact=s) | Q(name__iexact=s)).first() \
                    if not s.isdigit() else self.visible.filter(pk=int(s)).first()
                if p is None:
                    raise JQLError(f"El proyecto «{s}» no existe o no tienes acceso")
                ids.append(p.id)
            return eq_neg(Q(project_id__in=ids))

        if f == "key":
            if op in (">", ">=", "<", "<="):
                s = str(vals[0]).upper()
                if "-" not in s:
                    raise JQLError("Clave inválida")
                pkey, num = s.rsplit("-", 1)
                lookup = {">": "gt", ">=": "gte", "<": "lt", "<=": "lte"}[op]
                return Q(project__key=pkey, **{f"number__{lookup}": int(num)})
            keys = [str(v).upper() for v in vals]
            return eq_neg(Q(key__in=keys))

        if f == "id":
            try:
                ids = [int(str(v)) for v in vals]
            except ValueError as e:
                raise JQLError("id debe ser numérico") from e
            if op in (">", ">=", "<", "<="):
                lookup = {">": "gt", ">=": "gte", "<": "lt", "<=": "lte"}[op]
                return Q(**{f"id__{lookup}": ids[0]})
            return eq_neg(Q(id__in=ids))

        if f == "type":
            return eq_neg(Q(issue_type_id__in=self.resolve_named(IssueType, vals, "tipo")))
        if f == "status":
            return eq_neg(Q(status_id__in=self.resolve_named(Status, vals, "estado")))
        if f == "statuscategory":
            cats = []
            for v in vals:
                cat = STATUS_CATEGORY_ALIASES.get(str(v).lower())
                if not cat:
                    raise JQLError(f"Categoría inválida: «{v}»")
                cats.append(cat)
            return eq_neg(Q(status__category__in=cats))
        if f == "priority":
            ids = self.resolve_named(Priority, vals, "prioridad")
            if op in (">", ">=", "<", "<="):
                pos = Priority.objects.get(pk=ids[0]).position
                # higher priority = lower position
                lookup = {">": "lt", ">=": "lte", "<": "gt", "<=": "gte"}[op]
                return Q(**{f"priority__position__{lookup}": pos})
            return eq_neg(Q(priority_id__in=ids))
        if f == "resolution":
            ids = [] if any(str(v).lower() == "unresolved" for v in vals) else None
            if ids is not None:
                q = Q(resolution__isnull=True)
                return q if op in ("=", "in") else ~q
            return eq_neg(Q(resolution_id__in=self.resolve_named(Resolution, vals,
                                                                  "resolución")))
        if f in ("assignee", "reporter"):
            return eq_neg(Q(**{f"{f}_id__in": self.resolve_users(vals)}))
        if f == "watcher":
            return eq_neg(Q(watchers__id__in=self.resolve_users(vals)))
        if f == "voter":
            return eq_neg(Q(voters__id__in=self.resolve_users(vals)))
        if f == "labels":
            labels = [str(v) for v in vals]
            return eq_neg(Q(labels__overlap=labels))
        if f == "component":
            ids = self.resolve_named(Component, vals, "componente",
                                     Q(project__in=self.visible))
            return eq_neg(Q(components__id__in=ids))
        if f in ("fixversion", "affectedversion"):
            ids = self.resolve_named(Version, vals, "versión", Q(project__in=self.visible))
            path = "fix_versions" if f == "fixversion" else "affects_versions"
            return eq_neg(Q(**{f"{path}__id__in": ids}))
        if f == "sprint":
            ids = self.resolve_named(Sprint, vals, "sprint",
                                     Q(board__project__in=self.visible))
            return eq_neg(Q(sprint_id__in=ids) | Q(closed_sprints__id__in=ids))
        if f == "parent":
            ids = []
            for v in vals:
                s = str(v).upper()
                visible_issues = Issue.objects.filter(project__in=self.visible)
                obj = visible_issues.filter(pk=int(s)).first() if s.isdigit() else \
                    visible_issues.filter(key=s).first()
                if obj is None:
                    raise JQLError(f"La incidencia «{v}» no existe o no tienes acceso")
                ids.append(obj.id)
            return eq_neg(Q(parent_id__in=ids))
        if f == "team":
            from apps.plans.models import Team

            return eq_neg(Q(team_id__in=self.resolve_named(Team, vals, "equipo")))
        if f == "flagged":
            v = str(vals[0]).lower() in ("true", "1", "yes", "si", "sí", "impediment")
            return eq_neg(Q(flagged=v))

        cmp_lookups = {">": GreaterThan, ">=": GreaterThanOrEqual, "<": LessThan,
                       "<=": LessThanOrEqual}
        if f in DURATION_FIELDS:  # originalEstimate > 2h, timeSpent >= "1d 4h", … = 30
            path = DURATION_FIELDS[f]
            secs = [self.parse_duration(v) for v in vals]
            if op in cmp_lookups:
                return Q(**{f"{path}__{cmp_lookups[op].lookup_name}": secs[0]})
            return eq_neg(Q(**{f"{path}__in": secs}))
        if f in ("workratio", "votes"):  # workRatio > 75, votes >= 2
            expr = _work_ratio() if f == "workratio" else _count_of("voters")
            nums = []
            for v in vals:
                if not re.fullmatch(r"-?\d+(\.\d+)?" if f == "workratio" else r"\d+", str(v)):
                    raise JQLError(f"Se esperaba un número en {c.field}: «{v}»")
                nums.append(float(v) if f == "workratio" else int(v))
            if op in cmp_lookups:
                return Q(cmp_lookups[op](expr, nums[0]))
            q = Q(Exact(expr, nums[0]))
            for n in nums[1:]:
                q |= Q(Exact(expr, n))
            return eq_neg(q)
        if f == "lastviewed":  # lastViewed >= -1w (the requesting user's views)
            expr = self.last_viewed()
            dt = self.parse_date(vals[0])
            if op in ("=", "!="):
                start = timezone.make_aware(datetime.combine(timezone.localtime(dt).date(),
                                                             time.min))
                q = Q(GreaterThanOrEqual(expr, start)) & Q(LessThan(expr,
                                                                      start + timedelta(days=1)))
                return q if op == "=" else ~q
            if op not in cmp_lookups:
                raise JQLError(f"Operador «{c.op}» inválido para fechas")
            return Q(cmp_lookups[op](expr, dt))

        if f in ("created", "updated", "resolved", "due", "startdate"):
            path = {"created": "created_at", "updated": "updated_at", "resolved": "resolved_at",
                    "due": "due_date", "startdate": "start_date"}[f]
            is_date = f in ("due", "startdate")
            dt = self.parse_date(vals[0])
            value = timezone.localtime(dt).date() if is_date else dt
            if op in ("=", "!="):
                if is_date:
                    q = Q(**{path: value})
                else:
                    day = timezone.localtime(dt).date()
                    start = timezone.make_aware(datetime.combine(day, time.min))
                    q = Q(**{f"{path}__gte": start, f"{path}__lt": start + timedelta(days=1)})
                return q if op == "=" else ~q
            lookup = {">": "gt", ">=": "gte", "<": "lt", "<=": "lte"}.get(op)
            if lookup is None:
                raise JQLError(f"Operador «{c.op}» inválido para fechas")
            return Q(**{f"{path}__{lookup}": value})

        if f == "storypoints" or f.startswith("cf["):
            path = "story_points" if f == "storypoints" else f"custom_fields__{f[3:-1]}"
            if op in (">", ">=", "<", "<="):
                try:
                    num = Decimal(str(vals[0]))
                except InvalidOperation as e:
                    raise JQLError("Se esperaba un número") from e
                lookup = {">": "gt", ">=": "gte", "<": "lt", "<=": "lte"}[op]
                return Q(**{f"{path}__{lookup}": float(num) if f.startswith("cf[") else num})
            if op in ("~", "!~"):
                q = Q(**{f"{path}__icontains": str(vals[0])})
                return q if op == "~" else ~q
            if f.startswith("cf["):
                q = Q()
                for v in vals:
                    s = str(v)
                    q |= Q(**{path: s}) | Q(**{f"{path}__contains": [s]})
                    try:
                        q |= Q(**{path: float(s)})
                    except ValueError:
                        pass
                return eq_neg(q)
            try:
                nums = [Decimal(str(v)) for v in vals]
            except InvalidOperation as e:
                raise JQLError("Se esperaba un número") from e
            return eq_neg(Q(story_points__in=nums))

        raise JQLError(f"El campo «{c.field}» no se puede consultar")

    def order_terms(self, f: str, raw: str) -> list:
        """Sort keys of a canonical field name, most significant first."""
        if f == "key":
            return [F("project__key"), F("number")]
        if f in ORDERABLE:
            return [F(ORDERABLE[f])]
        if f == "sprint":  # sprints without a start date go after the dated ones, by id
            return [F("sprint__start_date"), F("sprint_id")]
        if f == "parent":
            return [F("parent__project__key"), F("parent__number")]
        if f == "labels":
            return [_SqlTemplate(_LABELS_SQL, TextField(), labels=F("labels"))]
        if f == "component":
            return [_components_sort()]
        if f in ("fixversion", "affectedversion"):
            return [_versions_sort("fix_versions" if f == "fixversion" else "affects_versions")]
        if f == "resolution":  # catalogue order; unresolved = EMPTY
            return [F("resolution__position"), F("resolution_id")]
        if f == "timespent":  # no work logged = EMPTY (the model stores 0)
            return [NullIf(F("time_spent"), Value(0))]
        if f == "workratio":
            return [_work_ratio()]
        if f == "flagged":  # Jira's «Impediment» checkbox: flagged first in ASC
            return [_SqlTemplate("(CASE WHEN {f} THEN 1 END)", IntegerField(), f=F("flagged"))]
        if f in ("votes", "voter"):
            return [_count_of("voters")]
        if f == "watcher":
            return [_count_of("watchers")]
        if f == "lastviewed":
            return [self.last_viewed()]
        m = _CF_RE.fullmatch(f)
        if m:
            cf = self.custom_field(int(m.group(1)))
            if cf is None:
                raise JQLError(f"El campo «{raw}» no existe")
            return [_custom_field_sort(cf)]
        raise JQLError(f"No se puede ordenar por «{raw}»")

    def order(self, items: list[tuple[str, bool]]) -> list:
        from apps.issues.models import CustomField

        # one query for every cf[ID] of the ORDER BY (names resolve in field_name)
        ids = {int(m.group(1)) for raw, _ in items
               if (m := _CF_RE.fullmatch(raw.strip().lower()))} - set(self._custom_fields)
        if ids:
            found = {c.id: c for c in CustomField.all_objects.filter(pk__in=ids)}
            self._custom_fields.update({i: found.get(i) for i in ids})
        out = []
        for raw, desc in items:
            f = self.field_name(raw) if raw.strip().lower() != "rank" else "rank"
            for expr in self.order_terms(f, raw):  # EMPTY is the greatest value, like Jira
                out.append(expr.desc(nulls_first=True) if desc else expr.asc(nulls_last=True))
        return out


def compile_jql(jql: str, *, user=None, project=None) -> CompiledQuery:
    parsed = parse(jql)
    comp = _Compiler(user, project)
    q = comp.compile(parsed.where)
    order = comp.order(parsed.order) if parsed.order else []
    return CompiledQuery(q, order)


def search_issues(user, jql: str):
    """Return a queryset of issues visible to `user` matching `jql`."""
    from apps.issues.models import Issue
    from apps.projects.permissions import visible_projects

    compiled = compile_jql(jql, user=user)
    qs = Issue.objects.filter(project__in=visible_projects(user), is_archived=False).filter(
        compiled.q)
    order = compiled.order_by or ["-created_at"]
    return qs.distinct().order_by(*order, "-id")
