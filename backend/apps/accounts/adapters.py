from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings


def _email_allowed(email: str | None) -> bool:
    domains = settings.ALLOWED_SIGNUP_DOMAINS
    if not domains:
        return False  # invite-only: accounts created by admins
    if not email or "@" not in email:
        return False
    return email.rsplit("@", 1)[1].lower() in domains


class AccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        # Domain itself is validated in clean_email (headless sends JSON bodies).
        return bool(settings.ALLOWED_SIGNUP_DOMAINS)

    def clean_email(self, email):
        email = super().clean_email(email)
        if not _email_allowed(email):
            from django import forms

            raise forms.ValidationError("Este dominio de correo no está autorizado.")
        return email.lower()

    def save_user(self, request, user, form, commit=True):
        user = super().save_user(request, user, form, commit=False)
        user.email = user.email.lower()
        if commit:
            user.save()
        return user


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    def is_open_for_signup(self, request, sociallogin):
        return _email_allowed(sociallogin.user.email)

    def populate_user(self, request, sociallogin, data):
        user = super().populate_user(request, sociallogin, data)
        name = data.get("name") or " ".join(
            p for p in [data.get("first_name"), data.get("last_name")] if p
        )
        if name:
            user.full_name = name
        user.email = (user.email or "").lower()
        return user
