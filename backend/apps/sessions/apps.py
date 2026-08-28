from __future__ import annotations

from django.apps import AppConfig


class SessionsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.sessions"
    # Explicit, not derived from `name`: the default label ("sessions") would
    # collide with django.contrib.sessions, which this project also uses (for
    # the admin site's login).
    label = "customer_sessions"
    verbose_name = "Customer sessions"

    def ready(self) -> None:
        # Registers projections that turn person_entered / person_exited /
        # camera_stats events into CustomerSession rows -- see
        # apps.cameras.apps.CamerasConfig.ready for why this import lives here
        # rather than at module load time.
        from apps.sessions import projections  # noqa: F401
