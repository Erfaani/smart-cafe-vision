from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.accounts.views import (
    LoginView,
    LogoutView,
    MeView,
    PasswordChangeView,
    RefreshView,
    UserViewSet,
)

router = DefaultRouter()
router.register("users", UserViewSet, basename="user")

urlpatterns = [
    path("login/", LoginView.as_view(), name="auth-login"),
    path("refresh/", RefreshView.as_view(), name="auth-refresh"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
    path("me/", MeView.as_view(), name="auth-me"),
    path("password/", PasswordChangeView.as_view(), name="auth-password"),
    path("", include(router.urls)),
]
