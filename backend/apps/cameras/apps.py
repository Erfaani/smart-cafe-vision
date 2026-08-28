from __future__ import annotations

from django.apps import AppConfig


class CamerasConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.cameras"
    verbose_name = "Cameras"

    def ready(self) -> None:
        # Registers projections that turn camera_connected / camera_disconnected
        # / camera_stats events into updates on the Camera row. Imported here,
        # not at module load time, so it runs exactly once the app registry is
        # ready (projections touch the Camera model).
        from apps.cameras import projections  # noqa: F401
