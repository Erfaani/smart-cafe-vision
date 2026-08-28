"""Credential redaction shared by the backend and the AI worker.

The worker opens streams with `rtsp://user:pass@host/path` (OpenCV has no
separate auth parameter for RTSP), and both FFmpeg and OpenCV echo that full
URL back verbatim in their error strings on a bad connection. Anything that
touches those errors -- a log line, an event payload -- must redact them, so
the implementation lives once here rather than being re-derived on each side.
"""
from __future__ import annotations

import re

_RTSP_CREDENTIALS = re.compile(r"(rtsp://[^:/@\s]+:)([^@\s]+)(@)", re.IGNORECASE)


def redact_rtsp_credentials(text: str) -> str:
    """Replace the password in any `rtsp://user:pass@host` substring with `***`."""
    return _RTSP_CREDENTIALS.sub(r"\1***\3", text)
