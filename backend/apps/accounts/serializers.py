from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    cafe_slug = serializers.CharField(source="cafe.slug", read_only=True, default=None)
    cafe_name = serializers.CharField(source="cafe.name", read_only=True, default=None)
    display_name = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "full_name",
            "display_name",
            "role",
            "cafe",
            "cafe_slug",
            "cafe_name",
            "is_active",
            "is_superuser",
            "last_login",
            "date_joined",
        )
        read_only_fields = ("id", "is_superuser", "last_login", "date_joined")


class UserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    class Meta:
        model = User
        fields = ("id", "email", "full_name", "role", "cafe", "password", "is_active")
        read_only_fields = ("id",)

    def validate_password(self, value: str) -> str:
        try:
            validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc
        return value

    def create(self, validated_data: dict):
        password = validated_data.pop("password")
        return User.objects.create_user(password=password, **validated_data)


class PasswordResetResponseSerializer(serializers.Serializer):
    """Schema-doc only, for UserViewSet.reset_password -- a generated
    password, shown exactly once, same shape as `manage.py bootstrap`'s
    generated owner password."""

    password = serializers.CharField()


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)

    def validate_current_password(self, value: str) -> str:
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def validate_new_password(self, value: str) -> str:
        try:
            validate_password(value, self.context["request"].user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc
        return value

    def save(self, **kwargs):
        user = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password", "updated_at"])
        return user


class LoginSerializer(TokenObtainPairSerializer):
    """Email/password login that also returns the profile.

    The dashboard needs role and café on the very first paint (to decide which
    navigation to render); returning them with the token avoids a second
    round-trip on every login.
    """

    username_field = User.USERNAME_FIELD

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        # Claims kept deliberately minimal: enough for the websocket layer to
        # scope a subscription, nothing that would leak if a token is captured.
        token["role"] = user.role
        token["cafe"] = str(user.cafe_id) if user.cafe_id else None
        return token

    def validate(self, attrs: dict) -> dict:
        attrs[self.username_field] = attrs.get(self.username_field, "").strip().lower()
        data = super().validate(attrs)
        data["user"] = UserSerializer(self.user).data
        return data


# --------------------------------------------------------------------------- #
# Schema-only serializers
#
# The auth endpoints are APIViews, which drf-spectacular cannot introspect. These
# exist so /api/docs/ documents the real request and response shapes instead of
# quietly omitting the endpoints a café integrator most needs.
# --------------------------------------------------------------------------- #
class LoginRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, style={"input_type": "password"})


class LoginResponseSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()
    user = UserSerializer()


class LogoutRequestSerializer(serializers.Serializer):
    refresh = serializers.CharField(required=False, allow_blank=True)


class ErrorDetailSerializer(serializers.Serializer):
    code = serializers.CharField()
    message = serializers.CharField()
    detail = serializers.JSONField(required=False)


class ErrorEnvelopeSerializer(serializers.Serializer):
    error = ErrorDetailSerializer()
