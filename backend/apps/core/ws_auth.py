"""WebSocket authentication middleware.

Browsers cannot set an Authorization header on a WebSocket handshake, so the
access token arrives as a query parameter. That is acceptable here because the
token is short-lived and the connection stays on the café LAN, but it does mean
the URL must never be logged verbatim -- RedactSecretsFilter handles that.

Session cookies still work too (AuthMiddlewareStack wraps this), which is what
the Django admin and same-origin pages use.
"""
from __future__ import annotations

import logging
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser

logger = logging.getLogger("smartcafe.ws")


@database_sync_to_async
def _user_from_token(raw_token: str):
    from django.contrib.auth import get_user_model
    from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
    from rest_framework_simplejwt.tokens import AccessToken

    try:
        token = AccessToken(raw_token)
    except (InvalidToken, TokenError):
        logger.info("ws_auth_rejected reason=invalid_token")
        return AnonymousUser()

    user_id = token.get("user_id")
    if not user_id:
        return AnonymousUser()
    try:
        user = get_user_model().objects.get(pk=user_id)
    except get_user_model().DoesNotExist:
        return AnonymousUser()
    if not user.is_active:
        return AnonymousUser()
    return user


class JWTAuthMiddleware(BaseMiddleware):
    """Populate scope['user'] from a `?token=` access token when present."""

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "websocket":
            query = parse_qs(scope.get("query_string", b"").decode())
            token = (query.get("token") or [""])[0]
            if token:
                scope["user"] = await _user_from_token(token)
            elif "user" not in scope:
                scope["user"] = AnonymousUser()
        return await super().__call__(scope, receive, send)


def JWTAuthMiddlewareStack(inner):
    """Session cookies first, then a JWT query parameter as an override."""
    from channels.auth import AuthMiddlewareStack

    return JWTAuthMiddleware(AuthMiddlewareStack(inner))
