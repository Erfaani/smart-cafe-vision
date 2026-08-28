from __future__ import annotations

import logging
import secrets

from django.contrib.auth import get_user_model
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView

from apps.accounts.serializers import (
    ErrorEnvelopeSerializer,
    LoginRequestSerializer,
    LoginResponseSerializer,
    LoginSerializer,
    LogoutRequestSerializer,
    PasswordChangeSerializer,
    PasswordResetResponseSerializer,
    UserCreateSerializer,
    UserSerializer,
)
from apps.core.permissions import IsOwnerOrManager
from apps.core.viewsets import CafeScopedCreateMixin

logger = logging.getLogger("smartcafe.auth")
User = get_user_model()


@extend_schema(
    tags=["auth"],
    request=LoginRequestSerializer,
    responses={200: LoginResponseSerializer, 401: ErrorEnvelopeSerializer},
)
class LoginView(APIView):
    """Exchange email + password for an access/refresh pair."""

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_scope = "login"

    def post(self, request: Request) -> Response:
        serializer = LoginSerializer(data=request.data, context={"request": request})
        try:
            credentials_ok = serializer.is_valid()
        except AuthenticationFailed:
            # simplejwt raises rather than returning False. Letting it escape
            # would produce a 403 (DRF downgrades 401 when no authenticator can
            # supply a WWW-Authenticate header), which is the wrong status and
            # confuses every HTTP client.
            credentials_ok = False

        if not credentials_ok:
            # Log the attempt, never the credentials.
            logger.warning(
                "login_failed email=%s ip=%s",
                str(request.data.get("email", ""))[:120],
                request.META.get("REMOTE_ADDR", "-"),
            )
            return Response(
                {"error": {"code": "invalid_credentials", "message": "Invalid email or password."}},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        logger.info("login_ok user=%s", serializer.user.email)
        return Response(serializer.validated_data, status=status.HTTP_200_OK)


@extend_schema(tags=["auth"])
class RefreshView(TokenRefreshView):
    throttle_scope = "token_refresh"


@extend_schema(tags=["auth"], request=LogoutRequestSerializer, responses={204: None})
class LogoutView(APIView):
    """Best-effort logout.

    Token blacklisting is intentionally off (spec §16: the café must keep
    working without external services, and a blacklist table adds a database
    write to every refresh). The client discards its cookies; access tokens
    expire in 30 minutes. If a deployment needs immediate revocation, enable
    simplejwt's blacklist app and flip BLACKLIST_AFTER_ROTATION.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        raw = request.data.get("refresh")
        if raw:
            try:
                RefreshToken(raw)  # validate shape so a bad client is visible in logs
            except TokenError:
                logger.info("logout_with_invalid_refresh user=%s", request.user.email)
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["auth"], responses={200: UserSerializer})
class MeView(APIView):
    """Current user profile; the dashboard's session check."""

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        return Response(UserSerializer(request.user).data)

    @extend_schema(request=UserSerializer, responses={200: UserSerializer})
    def patch(self, request: Request) -> Response:
        serializer = UserSerializer(
            request.user,
            data={"full_name": request.data.get("full_name", request.user.full_name)},
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


@extend_schema(
    tags=["auth"],
    request=PasswordChangeSerializer,
    responses={204: None, 400: ErrorEnvelopeSerializer},
)
class PasswordChangeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        serializer = PasswordChangeSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        logger.info("password_changed user=%s", request.user.email)
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["auth"])
class UserViewSet(CafeScopedCreateMixin, viewsets.ModelViewSet):
    """Staff account management, scoped to the caller's café."""

    permission_classes = [IsOwnerOrManager]
    # Declared for schema generation only; get_queryset() below is what runs.
    queryset = User.objects.none()

    def get_serializer_class(self):
        return UserCreateSerializer if self.action == "create" else UserSerializer

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser:
            return User.objects.all()
        if not user.cafe_id:
            return User.objects.filter(pk=user.pk)
        return User.objects.filter(cafe_id=user.cafe_id)

    @extend_schema(request=None, responses={200: UserSerializer, 400: ErrorEnvelopeSerializer})
    @action(detail=True, methods=["post"], url_path="deactivate")
    def deactivate(self, request: Request, pk: str | None = None) -> Response:
        user = self.get_object()
        if user.pk == request.user.pk:
            return Response(
                {"error": {"code": "self_deactivation", "message": "You cannot deactivate your own account."}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user.is_active = False
        user.save(update_fields=["is_active", "updated_at"])
        return Response(UserSerializer(user).data)

    @extend_schema(request=None, responses={200: PasswordResetResponseSerializer})
    @action(detail=True, methods=["post"], url_path="reset-password")
    def reset_password(self, request: Request, pk: str | None = None) -> Response:
        """Sets a new, randomly generated password on a staff account and
        returns it once.

        There is no self-service "forgot password" flow: the product has no
        email service to send a reset link through (spec §16 -- a café must
        keep working with no internet at all), so recovery is an
        owner/manager action instead, in the same "generated, shown once,
        never stored or logged" shape as `manage.py bootstrap`'s generated
        owner password.
        """
        user = self.get_object()
        password = secrets.token_urlsafe(12)
        user.set_password(password)
        user.save(update_fields=["password", "updated_at"])
        logger.info("password_reset_by_admin target_user=%s by=%s", user.email, request.user.email)
        return Response({"password": password})
