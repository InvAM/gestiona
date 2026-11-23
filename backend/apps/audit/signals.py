from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from .models import AuditEntry
from .services import record


@receiver(user_logged_in)
def on_login(sender, request, user, **kwargs):
    record(request=request, actor=user, category=AuditEntry.Category.AUTH,
           action="Inicio de sesión", object_repr=user.email)


@receiver(user_logged_out)
def on_logout(sender, request, user, **kwargs):
    if user is not None:
        record(request=request, actor=user, category=AuditEntry.Category.AUTH,
               action="Cierre de sesión", object_repr=user.email)


@receiver(user_login_failed)
def on_login_failed(sender, credentials, request=None, **kwargs):
    email = str(credentials.get("email") or credentials.get("username") or "")[:200]
    record(request=request, category=AuditEntry.Category.AUTH,
           action="Inicio de sesión fallido", object_repr=email)
