from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.display.views import (
    PublicDisplayLiveView,
    PublicDisplayMessagesView,
    PublicDisplayStatsView,
)
from apps.tenants.views import CafeViewSet, PublicCafeView

router = DefaultRouter()
router.register("", CafeViewSet, basename="cafe")

urlpatterns = [
    path("public/<slug:slug>/", PublicCafeView.as_view(), name="public-cafe"),
    # Phase 7: the rest of what the public display needs, alongside the
    # branding above -- separate views (apps.display owns this domain) but
    # the same public/<slug>/ prefix, since a kiosk browser has no other
    # identity than "which café."
    path("public/<slug:slug>/live/", PublicDisplayLiveView.as_view(), name="public-cafe-live"),
    path("public/<slug:slug>/stats/", PublicDisplayStatsView.as_view(), name="public-cafe-stats"),
    path(
        "public/<slug:slug>/messages/",
        PublicDisplayMessagesView.as_view(),
        name="public-cafe-messages",
    ),
    path("", include(router.urls)),
]
