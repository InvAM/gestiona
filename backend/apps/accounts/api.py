from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.middleware.csrf import get_token
from ninja import File, Router, Schema, UploadedFile

from apps.core.errors import Forbidden, NotFound, ValidationFailed
from apps.core.schemas import UserRef, user_ref

router = Router(tags=["accounts"])
User = get_user_model()


class MeOut(UserRef):
    job_title: str
    timezone: str
    locale: str
    is_admin: bool
    is_superuser: bool
    can_create_projects: bool


class MeIn(Schema):
    full_name: str | None = None
    job_title: str | None = None
    timezone: str | None = None
    locale: str | None = None


class UserAdminOut(UserRef):
    job_title: str
    is_admin: bool
    last_login: str | None
    date_joined: str


class UserCreateIn(Schema):
    email: str
    full_name: str = ""
    is_admin: bool = False
    send_invite: bool = True


class UserUpdateIn(Schema):
    full_name: str | None = None
    job_title: str | None = None
    is_active: bool | None = None
    is_admin: bool | None = None


class AuthConfigOut(Schema):
    password_login: bool
    signup_open: bool
    providers: list[str]
    provider_names: dict[str, str] = {}
    csrf_token: str


def _me(u) -> dict:
    from apps.projects.services import can_create_projects

    return {
        **user_ref(u), "job_title": u.job_title, "timezone": u.timezone, "locale": u.locale,
        "is_admin": u.is_staff or u.is_superuser, "is_superuser": u.is_superuser,
        "can_create_projects": can_create_projects(u),
    }


def _admin_user(u) -> dict:
    return {
        **user_ref(u), "job_title": u.job_title, "is_admin": u.is_staff,
        "last_login": u.last_login.isoformat() if u.last_login else None,
        "date_joined": u.date_joined.isoformat(),
    }


def _require_admin(user):
    if not (user.is_staff or user.is_superuser):
        raise Forbidden("Solo administradores")


@router.get("/auth/config", auth=None, response=AuthConfigOut)
def auth_config(request):
    """Public: what login options the frontend should show. Also sets the CSRF cookie."""
    return {
        "password_login": not settings.SOCIALACCOUNT_ONLY,
        "signup_open": bool(settings.ALLOWED_SIGNUP_DOMAINS),
        "providers": [
            p["APPS"][0]["provider_id"] if key == "openid_connect" else key
            for key, p in settings.SOCIALACCOUNT_PROVIDERS.items()
        ],
        "provider_names": {
            (p["APPS"][0]["provider_id"] if key == "openid_connect" else key):
            (p["APPS"][0].get("name") if key == "openid_connect" else key.title())
            for key, p in settings.SOCIALACCOUNT_PROVIDERS.items()
        },
        "csrf_token": get_token(request),
    }


class SetPasswordIn(Schema):
    uid: str
    token: str
    password: str


@router.post("/auth/set-password", auth=None, response=MeOut)
def set_password(request, data: SetPasswordIn):
    """Complete an invitation (or reset) link: sets password and logs the user in."""
    from django.contrib.auth import login
    from django.contrib.auth.password_validation import validate_password
    from django.contrib.auth.tokens import default_token_generator
    from django.core.exceptions import ValidationError
    from django.utils.http import urlsafe_base64_decode

    try:
        uid = int(urlsafe_base64_decode(data.uid).decode())
    except (ValueError, TypeError, UnicodeDecodeError) as e:
        raise ValidationFailed("Enlace inválido", code="invalid_link") from e
    user = User.objects.filter(pk=uid, is_active=True).first()
    if user is None or not default_token_generator.check_token(user, data.token):
        raise ValidationFailed("El enlace expiró o ya fue usado", code="invalid_link")
    try:
        validate_password(data.password, user)
    except ValidationError as e:
        raise ValidationFailed(" ".join(e.messages), code="password") from e
    user.set_password(data.password)
    user.save()
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return _me(user)


@router.get("/me", response=MeOut)
def me(request):
    return _me(request.user)


@router.patch("/me", response=MeOut)
def update_me(request, data: MeIn):
    u = request.user
    for k, v in data.dict(exclude_unset=True).items():
        if v is not None:
            setattr(u, k, v.strip() if isinstance(v, str) else v)
    if len(u.full_name) > 150:
        raise ValidationFailed("Nombre demasiado largo")
    u.save()
    return _me(u)


@router.post("/me/avatar", response=MeOut)
def upload_avatar(request, file: File[UploadedFile]):
    if file.size > 2 * 1024 * 1024:
        raise ValidationFailed("La imagen debe pesar menos de 2 MB")
    if (file.content_type or "") not in ("image/png", "image/jpeg", "image/webp", "image/gif"):
        raise ValidationFailed("Formato no soportado (PNG, JPG, WEBP, GIF)")
    from PIL import Image

    try:
        Image.open(file).verify()
    except Exception as e:
        raise ValidationFailed("La imagen no es válida") from e
    file.seek(0)
    u = request.user
    if u.avatar:
        u.avatar.delete(save=False)
    u.avatar.save(f"{u.id}-{file.name}"[-80:], file, save=True)
    return _me(u)


@router.delete("/me/avatar", response=MeOut)
def delete_avatar(request):
    u = request.user
    if u.avatar:
        u.avatar.delete(save=True)
    return _me(u)


@router.get("/users", response=list[UserRef])
def list_users(request, q: str = "", project: str | None = None, assignable: bool = False,
               limit: int = 20, include_inactive: bool = False):
    qs = User.objects.filter(is_bot=False)
    if not include_inactive:
        qs = qs.filter(is_active=True)
    if project:
        from apps.projects.models import Project
        from apps.projects.permissions import assignable_users, has_perm

        p = Project.objects.filter(key=project.upper()).first()
        if p is None or not has_perm(request.user, p, "browse"):
            raise NotFound("Proyecto no encontrado")
        if assignable:
            qs = assignable_users(p)
    if q:
        qs = qs.filter(Q(full_name__icontains=q) | Q(email__icontains=q))
    return [user_ref(u) for u in qs.order_by("full_name", "email")[: min(limit, 100)]]


@router.get("/users/{user_id}", response=UserRef)
def get_user(request, user_id: int):
    u = User.objects.filter(pk=user_id).first()
    if u is None:
        raise NotFound("Usuario no encontrado")
    return user_ref(u)


# ---------------------------------------------------------------- admin: API tokens (SCIM)

class ApiTokenOut(Schema):
    id: int
    name: str
    prefix: str
    scopes: list[str]
    created_at: str
    last_used_at: str | None
    revoked: bool


class ApiTokenIn(Schema):
    name: str


class ApiTokenCreated(ApiTokenOut):
    token: str
    scim_url: str


def _token_out(t) -> dict:
    return {"id": t.id, "name": t.name, "prefix": t.prefix, "scopes": t.scopes,
            "created_at": t.created_at.isoformat(),
            "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
            "revoked": t.revoked_at is not None}


@router.get("/admin/api-tokens", response=list[ApiTokenOut])
def list_tokens(request):
    from .models import ApiToken

    _require_admin(request.user)
    return [_token_out(t) for t in ApiToken.objects.all()]


@router.post("/admin/api-tokens", response={201: ApiTokenCreated})
def create_token(request, data: ApiTokenIn):
    from .models import ApiToken
    from .scim import hash_token, new_token

    _require_admin(request.user)
    name = data.name.strip()[:120]
    if not name:
        raise ValidationFailed("Ponle un nombre (p. ej. «Entra ID»)", code="name")
    clear = new_token()
    t = ApiToken.objects.create(name=name, prefix=clear[:10], token_hash=hash_token(clear),
                                scopes=["scim"], created_by=request.user)
    return 201, {**_token_out(t), "token": clear,
                 "scim_url": request.build_absolute_uri("/scim/v2")}


@router.delete("/admin/api-tokens/{token_id}", response={204: None})
def revoke_token(request, token_id: int):
    from django.utils import timezone

    from .models import ApiToken

    _require_admin(request.user)
    ApiToken.objects.filter(pk=token_id, revoked_at__isnull=True).update(
        revoked_at=timezone.now())
    return 204, None


# ---------------------------------------------------------------- admin: user management

@router.get("/admin/users", response=list[UserAdminOut])
def admin_list_users(request, q: str = ""):
    _require_admin(request.user)
    qs = User.objects.filter(is_bot=False)
    if q:
        qs = qs.filter(Q(full_name__icontains=q) | Q(email__icontains=q))
    return [_admin_user(u) for u in qs.order_by("-is_active", "full_name", "email")[:500]]


@router.post("/admin/users", response={201: UserAdminOut})
def admin_create_user(request, data: UserCreateIn):
    _require_admin(request.user)
    email = data.email.strip().lower()
    from django.core.validators import validate_email

    try:
        validate_email(email)
    except Exception as e:
        raise ValidationFailed("Email inválido") from e
    if User.objects.filter(email__iexact=email).exists():
        raise ValidationFailed("Ya existe un usuario con ese email")
    user = User.objects.create_user(email=email, full_name=data.full_name.strip(),
                                    is_staff=data.is_admin and request.user.is_superuser)
    user.set_unusable_password()
    user.save()
    from allauth.account.models import EmailAddress

    EmailAddress.objects.create(user=user, email=email, primary=True, verified=True)
    if data.send_invite:
        from .invites import send_invite

        send_invite(request, user, invited_by=request.user)
    return 201, _admin_user(user)


@router.patch("/admin/users/{user_id}", response=UserAdminOut)
def admin_update_user(request, user_id: int, data: UserUpdateIn):
    _require_admin(request.user)
    u = User.objects.filter(pk=user_id).first()
    if u is None:
        raise NotFound("Usuario no encontrado")
    # Admins (staff) may only manage regular users; admins/superusers need a superuser.
    if (u.is_superuser or u.is_staff) and u.id != request.user.id and \
            not request.user.is_superuser:
        raise Forbidden("Solo un superadministrador puede modificar a otro administrador")
    d = data.dict(exclude_unset=True)
    if d.get("is_active") is False and u.id == request.user.id:
        raise ValidationFailed("No puedes desactivarte a ti mismo")
    if "is_admin" in d:
        if not request.user.is_superuser:
            raise Forbidden("Solo un superadministrador puede cambiar administradores")
        u.is_staff = bool(d["is_admin"])
    if d.get("full_name") is not None:
        u.full_name = d["full_name"].strip()[:150]
    if d.get("job_title") is not None:
        u.job_title = d["job_title"].strip()[:120]
    if d.get("is_active") is not None:
        u.is_active = bool(d["is_active"])
    u.save()
    return _admin_user(u)


@router.post("/admin/users/{user_id}/invite", response={204: None})
def admin_resend_invite(request, user_id: int):
    _require_admin(request.user)
    u = User.objects.filter(pk=user_id, is_active=True).first()
    if u is None:
        raise NotFound("Usuario no encontrado")
    from .invites import send_invite

    send_invite(request, u, invited_by=request.user)
    return 204, None
