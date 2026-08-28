"""RTSP URL validation.

Credentials are rejected here, not merely stripped: `rtsp_url` is shown in
plain text throughout the dashboard (camera list, edit form, error messages),
so a URL that could carry a password must never be accepted into that field in
the first place. `rtsp_username` / `rtsp_password` are the only place a
credential is allowed to live.
"""
from __future__ import annotations

from urllib.parse import urlparse

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


def validate_rtsp_url(value: str) -> None:
    if "@" in value:
        raise ValidationError(
            _(
                "The RTSP URL must not contain a username or password. "
                "Use the separate username and password fields instead."
            ),
            code="rtsp_url_has_credentials",
        )

    parsed = urlparse(value)
    if parsed.scheme.lower() != "rtsp":
        raise ValidationError(
            _("The URL must use the rtsp:// scheme, e.g. rtsp://192.168.1.64:554/live."),
            code="rtsp_url_bad_scheme",
        )
    if not parsed.hostname:
        raise ValidationError(_("The URL is missing a host."), code="rtsp_url_no_host")
