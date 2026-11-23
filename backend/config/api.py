from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import ProtectedError, RestrictedError
from django.http import Http404
from ninja import NinjaAPI
from ninja.errors import AuthenticationError
from ninja.errors import ValidationError as NinjaValidationError
from ninja.security import django_auth

from apps.core.errors import ApiError
from apps.core.softdelete import protected_usages, usage_details, usage_message
from apps.search.jql import JQLError

api = NinjaAPI(
    title="Gestiona API",
    version="1.0.0",
    urls_namespace="api",
    auth=django_auth,
    docs_url="/docs",
)


def _err(request, status: int, code: str, message: str, details=None):
    return api.create_response(
        request, {"code": code, "message": message, "details": details}, status=status
    )


@api.exception_handler(ApiError)
def on_api_error(request, exc: ApiError):
    return _err(request, exc.status, exc.code, exc.message, exc.details)


@api.exception_handler(JQLError)
def on_jql_error(request, exc: JQLError):
    return _err(request, 400, "jql_error", exc.message, {"position": exc.position})


@api.exception_handler(NinjaValidationError)
def on_validation(request, exc: NinjaValidationError):
    return _err(request, 422, "validation_error", "Datos inválidos", exc.errors)


@api.exception_handler(DjangoValidationError)
def on_django_validation(request, exc: DjangoValidationError):
    details = exc.message_dict if hasattr(exc, "error_dict") else exc.messages
    msg = exc.messages[0] if exc.messages else "Datos inválidos"
    return _err(request, 422, "validation_error", msg, details)


@api.exception_handler(ProtectedError)
def on_protected(request, exc: ProtectedError):
    usages = protected_usages(exc.protected_objects)
    return _err(request, 409, "protected", usage_message(usages), usage_details(usages))


@api.exception_handler(RestrictedError)
def on_restricted(request, exc: RestrictedError):
    usages = protected_usages(exc.restricted_objects)
    return _err(request, 409, "protected", usage_message(usages), usage_details(usages))


@api.exception_handler(Http404)
def on_404(request, exc):
    return _err(request, 404, "not_found", "No encontrado")


@api.exception_handler(PermissionDenied)
def on_403(request, exc):
    return _err(request, 403, "forbidden", "Sin permiso")


@api.exception_handler(AuthenticationError)
def on_401(request, exc):
    return _err(request, 401, "unauthenticated", "Inicia sesión para continuar")


from apps.accounts.api import router as accounts_router  # noqa: E402
from apps.ai.api import router as ai_router  # noqa: E402
from apps.analytics.api import router as analytics_router  # noqa: E402
from apps.audit.api import router as audit_router  # noqa: E402
from apps.automation.api import router as automation_router  # noqa: E402
from apps.boards.api import router as boards_router  # noqa: E402
from apps.core.meta import router as meta_router  # noqa: E402
from apps.dashboards.api import router as dashboards_router  # noqa: E402
from apps.forms.api import router as forms_router  # noqa: E402
from apps.imports.api import router as imports_router  # noqa: E402
from apps.issues.api import router as issues_router  # noqa: E402
from apps.issues.fields_api import router as fields_router  # noqa: E402
from apps.listview.api import router as listview_router  # noqa: E402
from apps.notifications.api import router as notifications_router  # noqa: E402
from apps.plans.api import router as plans_router  # noqa: E402
from apps.projects.api import router as projects_router  # noqa: E402
from apps.search.api import router as search_router  # noqa: E402
from apps.workflows.api import router as workflows_router  # noqa: E402

api.add_router("/", accounts_router)
api.add_router("/", projects_router)
api.add_router("/", issues_router)
api.add_router("/", boards_router)
api.add_router("/", search_router)
api.add_router("/", notifications_router)
api.add_router("/", workflows_router)
api.add_router("/", imports_router)
api.add_router("/", automation_router)
api.add_router("/", dashboards_router)
api.add_router("/", audit_router)
api.add_router("/", forms_router)
api.add_router("/", ai_router)
api.add_router("/", meta_router)
api.add_router("/", analytics_router)
api.add_router("/", listview_router)
api.add_router("/", plans_router)
api.add_router("/", fields_router)


@api.get("/health", auth=None, tags=["system"])
def health(request):
    from django.db import connection

    with connection.cursor() as c:
        c.execute("select 1")
    return {"ok": True}
