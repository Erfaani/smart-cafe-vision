"""Uniform API error envelope.

Café staff and the AI worker both consume these errors; a single shape keeps
frontend error handling and worker retry logic simple.
"""
from __future__ import annotations

import logging
from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger("smartcafe.api")


class ServiceError(Exception):
    """Domain-level failure that maps to a 4xx with a stable machine code."""

    code = "service_error"
    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(self, message: str, *, code: str | None = None, detail: Any = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        self.detail = detail


class CameraConnectionError(ServiceError):
    code = "camera_connection_failed"
    status_code = status.HTTP_502_BAD_GATEWAY


def _envelope(code: str, message: str, detail: Any = None) -> dict[str, Any]:
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if detail is not None:
        body["error"]["detail"] = detail
    return body


def api_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    if isinstance(exc, ServiceError):
        return Response(
            _envelope(exc.code, exc.message, exc.detail), status=exc.status_code
        )

    if isinstance(exc, DjangoValidationError):
        return Response(
            _envelope("validation_error", "Validation failed.", exc.message_dict
                      if hasattr(exc, "message_dict") else exc.messages),
            status=status.HTTP_400_BAD_REQUEST,
        )

    if isinstance(exc, IntegrityError):
        # Do not echo the database message: it can contain column values.
        logger.warning("integrity_error path=%s", context.get("request"))
        return Response(
            _envelope("conflict", "The request conflicts with existing data."),
            status=status.HTTP_409_CONFLICT,
        )

    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    # Prefer the code DRF attached to the detail: Http404 and PermissionDenied
    # arrive as plain Django exceptions with no default_code of their own, and
    # a client should still see "not_found" rather than a generic "error".
    detail = response.data
    code = getattr(exc, "default_code", None)
    message = "Request failed."

    if isinstance(detail, dict) and "detail" in detail:
        inner = detail["detail"]
        code = getattr(inner, "code", None) or code
        message = str(inner)
        detail = None
    elif isinstance(detail, list) and len(detail) == 1:
        inner = detail[0]
        code = getattr(inner, "code", None) or code
        message = str(inner)
        detail = None
    elif isinstance(detail, dict):
        message = "Validation failed."

    response.data = _envelope(str(code or "error"), message, detail)
    return response
