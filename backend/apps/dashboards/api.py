from django.db import transaction
from django.db.models import Max, Q
from ninja import Router, Schema

from apps.core import softdelete
from apps.core.errors import Forbidden, NotFound, ValidationFailed
from apps.core.schemas import UserRef, user_ref
from apps.search.jql import JQLError

from .gadgets import DEFAULT_GADGETS, GROUP_FIELDS, gadget_data
from .models import Dashboard, Gadget

router = Router(tags=["dashboards"])


class GadgetOut(Schema):
    id: int
    kind: str
    kind_display: str
    title: str
    config: dict
    column: int
    position: int


class DashboardOut(Schema):
    id: int
    name: str
    description: str
    owner: UserRef | None
    visibility: str
    columns: int
    starred: bool
    can_edit: bool
    updated_at: str
    deleted_at: str | None = None
    gadgets: list[GadgetOut] = []


class DashboardIn(Schema):
    name: str
    description: str = ""
    visibility: str = Dashboard.Visibility.PRIVATE
    columns: int = 2
    template: str = "default"  # default | blank


class DashboardPatch(Schema):
    name: str | None = None
    description: str | None = None
    visibility: str | None = None
    columns: int | None = None


class GadgetIn(Schema):
    kind: str
    title: str = ""
    config: dict = {}
    column: int = 0


class GadgetPatch(Schema):
    title: str | None = None
    config: dict | None = None


class LayoutItem(Schema):
    id: int
    column: int
    position: int


class LayoutIn(Schema):
    gadgets: list[LayoutItem]


class GadgetPreviewIn(Schema):
    kind: str
    config: dict = {}


def _visible(user):
    return Dashboard.objects.filter(Q(owner=user) | Q(visibility=Dashboard.Visibility.PUBLIC))


def _can_edit(user, d: Dashboard) -> bool:
    return d.owner_id == user.id or (user.is_superuser and d.visibility == "public")


def _gadget_out(g: Gadget) -> dict:
    return {"id": g.id, "kind": g.kind, "kind_display": g.get_kind_display(), "title": g.title,
            "config": g.config, "column": g.column, "position": g.position}


def _out(d: Dashboard, user, *, gadgets=False) -> dict:
    out = {
        "id": d.id, "name": d.name, "description": d.description, "owner": user_ref(d.owner),
        "visibility": d.visibility, "columns": d.columns,
        "starred": d.starred_by.filter(pk=user.pk).exists(), "can_edit": _can_edit(user, d),
        "updated_at": d.updated_at.isoformat(), "deleted_at": softdelete.iso(d.deleted_at),
    }
    if gadgets:
        out["gadgets"] = [_gadget_out(g) for g in d.gadgets.all()]
    return out


def _get(user, did: int, *, edit=False) -> Dashboard:
    d = _visible(user).select_related("owner").filter(pk=did).first()
    if d is None:
        raise NotFound("Panel no encontrado")
    if edit and not _can_edit(user, d):
        raise Forbidden("Solo el propietario puede editar este panel")
    return d


def _clean(data: dict) -> dict:
    if "name" in data and data["name"] is not None:
        data["name"] = data["name"].strip()[:120]
        if not data["name"]:
            raise ValidationFailed("El nombre es obligatorio", code="name")
    if data.get("visibility") and data["visibility"] not in Dashboard.Visibility.values:
        raise ValidationFailed("Visibilidad inválida", code="visibility")
    if data.get("columns") is not None and data["columns"] not in (1, 2, 3):
        raise ValidationFailed("Columnas: 1, 2 o 3", code="columns")
    return {k: v for k, v in data.items() if v is not None}


def _check_gadget(user, kind: str, config: dict) -> None:
    if kind not in Gadget.Kind.values:
        raise ValidationFailed("Tipo de gadget desconocido", code="kind")
    gb = config.get("group_by")
    if gb and gb not in GROUP_FIELDS:
        raise ValidationFailed("Campo de agrupación inválido", code="config")
    try:
        gadget_data(user, kind, config)  # validates JQL / filter / board access
    except JQLError as e:
        raise ValidationFailed(f"JQL inválido: {e.message}", code="jql") from e


def _deleted_dashboards(user):
    """Papelera: your own deleted dashboards (system admins see every deleted one)."""
    qs = Dashboard.all_objects.deleted()
    return qs if softdelete.is_system_admin(user) else qs.filter(owner=user)


@router.get("/dashboards", response=list[DashboardOut])
def list_dashboards(request, q: str = "", deleted: bool = False):
    qs = (_deleted_dashboards(request.user) if deleted else _visible(request.user)) \
        .select_related("owner")
    if q:
        qs = qs.filter(name__icontains=q)
    return [_out(d, request.user) for d in qs]


@router.post("/dashboards", response={201: DashboardOut})
@transaction.atomic
def create_dashboard(request, data: DashboardIn):
    fields = _clean({"name": data.name, "description": data.description,
                     "visibility": data.visibility, "columns": data.columns})
    d = Dashboard.objects.create(owner=request.user, **fields)
    if data.template == "default":
        pos: dict[int, int] = {}
        for g in DEFAULT_GADGETS:
            col = min(g["column"], d.columns - 1)
            pos[col] = pos.get(col, -1) + 1
            Gadget.objects.create(dashboard=d, kind=g["kind"], title=g["title"],
                                  config=g.get("config", {}), column=col, position=pos[col])
    d.starred_by.add(request.user)
    return 201, _out(d, request.user, gadgets=True)


@router.get("/dashboards/{did}", response=DashboardOut)
def get_dashboard(request, did: int):
    return _out(_get(request.user, did), request.user, gadgets=True)


@router.patch("/dashboards/{did}", response=DashboardOut)
def update_dashboard(request, did: int, data: DashboardPatch):
    d = _get(request.user, did, edit=True)
    for k, v in _clean(data.dict(exclude_unset=True)).items():
        setattr(d, k, v)
    d.save()
    if d.columns:
        d.gadgets.filter(column__gte=d.columns).update(column=d.columns - 1)
    return _out(d, request.user, gadgets=True)


@router.delete("/dashboards/{did}", response={204: None})
def delete_dashboard(request, did: int):
    """Soft delete (gadgets are kept, so restoring brings the panel back as it was)."""
    _get(request.user, did, edit=True).soft_delete()
    return 204, None


@router.post("/dashboards/{did}/restore", response=DashboardOut)
def restore_dashboard(request, did: int):
    d = _deleted_dashboards(request.user).select_related("owner").filter(pk=did).first()
    if d is None:
        raise NotFound("Panel no encontrado")
    softdelete.restore(d)
    return _out(d, request.user, gadgets=True)


@router.post("/dashboards/{did}/copy", response={201: DashboardOut})
@transaction.atomic
def copy_dashboard(request, did: int):
    src = _get(request.user, did)
    d = Dashboard.objects.create(owner=request.user, name=f"Copia de {src.name}"[:120],
                                 description=src.description, columns=src.columns)
    for g in src.gadgets.all():
        Gadget.objects.create(dashboard=d, kind=g.kind, title=g.title, config=g.config,
                              column=g.column, position=g.position)
    return 201, _out(d, request.user, gadgets=True)


@router.post("/dashboards/{did}/star", response={204: None})
def star(request, did: int):
    _get(request.user, did).starred_by.add(request.user)
    return 204, None


@router.delete("/dashboards/{did}/star", response={204: None})
def unstar(request, did: int):
    _get(request.user, did).starred_by.remove(request.user)
    return 204, None


@router.post("/dashboards/{did}/gadgets", response={201: GadgetOut})
def add_gadget(request, did: int, data: GadgetIn):
    d = _get(request.user, did, edit=True)
    _check_gadget(request.user, data.kind, data.config)
    col = max(0, min(data.column, d.columns - 1))
    top = d.gadgets.filter(column=col).aggregate(m=Max("position"))["m"]
    g = Gadget.objects.create(dashboard=d, kind=data.kind, title=data.title.strip()[:120],
                              config=data.config, column=col,
                              position=(top + 1) if top is not None else 0)
    return 201, _gadget_out(g)


@router.patch("/dashboards/{did}/gadgets/{gid}", response=GadgetOut)
def update_gadget(request, did: int, gid: int, data: GadgetPatch):
    d = _get(request.user, did, edit=True)
    g = d.gadgets.filter(pk=gid).first()
    if g is None:
        raise NotFound("Gadget no encontrado")
    if data.config is not None:
        _check_gadget(request.user, g.kind, data.config)
        g.config = data.config
    if data.title is not None:
        g.title = data.title.strip()[:120]
    g.save()
    return _gadget_out(g)


@router.delete("/dashboards/{did}/gadgets/{gid}", response={204: None})
def delete_gadget(request, did: int, gid: int):
    _get(request.user, did, edit=True).gadgets.filter(pk=gid).delete()
    return 204, None


@router.put("/dashboards/{did}/layout", response=DashboardOut)
@transaction.atomic
def save_layout(request, did: int, data: LayoutIn):
    d = _get(request.user, did, edit=True)
    gadgets = {g.id: g for g in d.gadgets.all()}
    for item in data.gadgets:
        g = gadgets.get(item.id)
        if g is None:
            raise ValidationFailed("Gadget de otro panel")
        g.column = max(0, min(item.column, d.columns - 1))
        g.position = item.position
    Gadget.objects.bulk_update(gadgets.values(), ["column", "position"])
    return _out(d, request.user, gadgets=True)


@router.get("/dashboards/{did}/gadgets/{gid}/data", response=dict)
def get_gadget_data(request, did: int, gid: int):
    d = _get(request.user, did)
    g = d.gadgets.filter(pk=gid).first()
    if g is None:
        raise NotFound("Gadget no encontrado")
    try:
        return gadget_data(request.user, g.kind, g.config)
    except JQLError as e:
        raise ValidationFailed(f"JQL inválido: {e.message}", code="jql") from e


@router.post("/dashboard-gadgets/preview", response=dict)
def preview(request, data: GadgetPreviewIn):
    try:
        return gadget_data(request.user, data.kind, data.config)
    except JQLError as e:
        raise ValidationFailed(f"JQL inválido: {e.message}", code="jql") from e
