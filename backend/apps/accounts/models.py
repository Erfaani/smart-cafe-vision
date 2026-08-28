"""User model.

Email is the login identifier: café staff accounts are created by an owner, and
"which email do I log in with" is a question staff can answer, whereas an
invented username is not.

Note what is NOT here: nothing about customers. Customers are never users, never
named, and never stored as people -- see apps/events for the anonymous model.
"""
from __future__ import annotations

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import UUIDModel


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email: str, password: str | None, **extra):
        if not email:
            raise ValueError("An email address is required.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.full_clean(exclude=["password"], validate_unique=False)
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email: str, password: str | None = None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("role", User.Role.OWNER)
        if extra["is_staff"] is not True or extra["is_superuser"] is not True:
            raise ValueError("A superuser must have is_staff and is_superuser set.")
        return self._create_user(email, password, **extra)


class User(UUIDModel, AbstractBaseUser, PermissionsMixin):
    class Role(models.TextChoices):
        OWNER = "owner", _("Owner")
        MANAGER = "manager", _("Manager")
        STAFF = "staff", _("Staff")
        VIEWER = "viewer", _("Viewer")

    email = models.EmailField(unique=True, db_index=True)
    full_name = models.CharField(max_length=150, blank=True)
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.STAFF)

    # Null for a superuser/installer account that administers every café on the
    # server; set for ordinary staff, who see exactly one café.
    cafe = models.ForeignKey(
        "tenants.Cafe",
        on_delete=models.CASCADE,
        related_name="users",
        null=True,
        blank=True,
    )

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(
        default=False, help_text=_("Can sign in to the Django admin site.")
    )
    date_joined = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        ordering = ("email",)
        verbose_name = _("user")
        verbose_name_plural = _("users")

    def __str__(self) -> str:
        return self.email

    def save(self, *args, **kwargs):
        self.email = self.email.lower().strip()
        super().save(*args, **kwargs)

    @property
    def display_name(self) -> str:
        return self.full_name or self.email.split("@")[0]

    @property
    def can_manage(self) -> bool:
        return self.is_superuser or self.role in {self.Role.OWNER, self.Role.MANAGER}
