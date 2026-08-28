"""WebSocket URL routing.

Kept separate from asgi.py so apps can register sockets without touching the
server entrypoint.
"""
from __future__ import annotations

from django.urls import path

from apps.core.consumers import SystemStatusConsumer
from apps.display.consumers import DisplayConsumer

websocket_urlpatterns = [
    path("ws/system/", SystemStatusConsumer.as_asgi()),
    path("ws/display/<slug:slug>/", DisplayConsumer.as_asgi()),
]
