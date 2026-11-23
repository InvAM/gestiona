"""Invite flow: admin creates the account, user receives a link to set a password.

Uses Django's password reset token generator (single-use, expires with PASSWORD_RESET_TIMEOUT).
The frontend page /auth/set-password/<uid>/<token> calls POST /_allauth/... reset or our
endpoint `POST /api/v1/auth/set-password`.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode


def invite_link(user) -> str:
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    return f"{settings.FRONTEND_URL}/auth/set-password/{uid}/{token}"


def send_invite(request, user, *, invited_by) -> None:
    link = invite_link(user)
    sso = ""
    if settings.SOCIALACCOUNT_PROVIDERS:
        sso = "\nTambién puedes entrar con el inicio de sesión de tu organización (SSO).\n"
    body = (
        f"Hola {user.display_name},\n\n"
        f"{invited_by.display_name} te invitó a Gestiona.\n\n"
        f"Crea tu contraseña aquí: {link}\n{sso}\n"
        "Si no esperabas este correo, ignóralo.\n\n— Gestiona"
    )
    send_mail("Te invitaron a Gestiona", body, None, [user.email])
