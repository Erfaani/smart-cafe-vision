from __future__ import annotations

from django.apps import AppConfig


class TablesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.tables"
    verbose_name = "Table sessions"

    def ready(self) -> None:
        # Registers projections that turn table_occupied / table_released /
        # camera_stats events into TableSession rows -- see
        # apps.sessions.apps.SessionsConfig.ready for why this import lives
        # here rather than at module load time.
        from apps.tables import projections  # noqa: F401
