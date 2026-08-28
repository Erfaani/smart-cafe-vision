"""Request correlation middleware."""
from __future__ import annotations

import uuid
from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from apps.core.logging import request_id_var

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIDMiddleware:
    """Give every request an id, honouring one supplied upstream.

    The AI worker stamps its own id on ingest calls, which lets a single frame's
    journey (worker -> API -> websocket) be traced through one grep.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        incoming = request.headers.get(REQUEST_ID_HEADER, "").strip()
        # Bound length: the header is attacker-controlled and ends up in logs.
        request_id = incoming[:64] if incoming else uuid.uuid4().hex[:12]
        request.request_id = request_id
        token = request_id_var.set(request_id)
        try:
            response = self.get_response(request)
        finally:
            request_id_var.reset(token)
        response[REQUEST_ID_HEADER] = request_id
        return response
