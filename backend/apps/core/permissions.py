"""Role-based API permissions (spec §25)."""
from __future__ import annotations

import hmac

from django.conf import settings
from rest_framework.permissions import SAFE_METHODS, BasePermission


class IsOwnerOrManager(BasePermission):
    """Write access for café owners and managers; read for any staff member."""

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        return user.is_superuser or user.role in {"owner", "manager"}


class IsOwner(BasePermission):
    """Reserved for destructive or tenant-level operations."""

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and (user.is_superuser or user.role == "owner"))


class IsAIWorker(BasePermission):
    """Authenticates the AI worker by shared service token.

    The worker is a machine on the same LAN, not a person: it gets a dedicated
    token rather than a user account so its access can be rotated independently
    and never inherits dashboard privileges.
    """

    def has_permission(self, request, view) -> bool:
        expected = settings.AI_WORKER_TOKEN
        if not expected:
            return False
        header = request.headers.get("X-Worker-Token", "")
        # Constant-time comparison to avoid leaking the token by timing.
        return hmac.compare_digest(header, expected)
