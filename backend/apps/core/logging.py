"""Logging filters (spec §28).

Two concerns, deliberately separated:
  * correlate every log line of one request/event with an id
  * never let an RTSP password or an auth token reach a log file

The redaction runs as a logging *filter* rather than inside a formatter so it
applies to every handler a deployment might add later (file, syslog, Sentry).
"""
from __future__ import annotations

import contextvars
import logging
import re

from scv_contracts.redact import redact_rtsp_credentials

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)


class RequestIDFilter(logging.Filter):
    """Attach the current request id to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = request_id_var.get()
        return True


# key=value and "key": "value" pairs. The value alternation includes an auth
# scheme prefix so `Authorization: Bearer <jwt>` redacts the whole token instead
# of just the word "Bearer".
_SENSITIVE_KEYS = re.compile(
    r"""(?ix)
    ( ["']? \b (?: password | passwd | secret | token | authorization | api[_-]?key ) \b ["']?
      \s* [:=] \s* )
    ( "[^"]*" | '[^']*' | (?: bearer | basic | token ) \s+ \S+ | [^\s,;}]+ )
    """
)

# A bare credential with no key in front of it, e.g. a raw header dump.
_AUTH_SCHEME = re.compile(r"(?i)\b(bearer|basic)\s+([A-Za-z0-9\-._~+/=]{8,})")


def scrub(text: str) -> str:
    """Redact credentials from an arbitrary log string.

    The RTSP part is shared with the AI worker (both processes build
    credential-bearing URLs); the rest is web-request-shaped and stays local to
    the backend.
    """
    text = redact_rtsp_credentials(text)
    text = _SENSITIVE_KEYS.sub(r"\1***", text)
    return _AUTH_SCHEME.sub(r"\1 ***", text)


class RedactSecretsFilter(logging.Filter):
    """Scrub credentials from the message and its arguments before formatting."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = scrub(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    key: scrub(value) if isinstance(value, str) else value
                    for key, value in record.args.items()
                }
            else:
                record.args = tuple(
                    scrub(arg) if isinstance(arg, str) else arg for arg in record.args
                )
        return True
