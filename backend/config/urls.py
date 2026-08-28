"""Root URL configuration.

Everything the product exposes lives under /api/v1/ so the whole surface can be
versioned at once; operational endpoints (health, schema) sit outside it.
"""
from __future__ import annotations

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

from apps.core.views import HealthView, ReadinessView

urlpatterns = [
    path("admin/", admin.site.urls),
    # Operational endpoints - unauthenticated by design so a monitoring probe or
    # a café technician can check the box without credentials. They expose
    # component status only, never café or customer data.
    path("healthz/", HealthView.as_view(), name="health"),
    path("readyz/", ReadinessView.as_view(), name="readiness"),
    # API
    path("api/v1/auth/", include("apps.accounts.urls")),
    path("api/v1/cafes/", include("apps.tenants.urls")),
    path("api/v1/events/", include("apps.events.urls")),
    path("api/v1/cameras/", include("apps.cameras.urls")),
    path("api/v1/sessions/", include("apps.sessions.urls")),
    path("api/v1/display-messages/", include("apps.display.urls")),
    path("api/v1/analytics/", include("apps.analytics.urls")),
    path("api/v1/tables/", include("apps.tables.urls")),
    # Schema / docs
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
