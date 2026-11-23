from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from apps.accounts import scim

from .api import api

admin.site.site_header = "Gestiona · Administración"
admin.site.site_title = "Gestiona"
admin.site.index_title = "Administración del sistema"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", api.urls),
    path("_allauth/", include("allauth.headless.urls")),
    path("accounts/", include("allauth.urls")),  # required for SSO provider callbacks
    # SCIM 2.0 user provisioning (Entra ID, Okta, ...)
    path("scim/v2/Users", scim.users),
    path("scim/v2/Users/<str:user_id>", scim.user_detail),
    path("scim/v2/Groups", scim.groups),
    path("scim/v2/ServiceProviderConfig", scim.service_provider_config),
    path("scim/v2/ResourceTypes", scim.resource_types),
]

if settings.DEBUG:
    from django.conf.urls.static import static

    urlpatterns += static(settings.MEDIA_URL + "avatars/", document_root=settings.MEDIA_ROOT /
                          "avatars")
