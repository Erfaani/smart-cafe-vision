"""System-status WebSocket.

Phase 1 ships the transport and the auth handshake only. Live tracking frames
are added in Phase 7; getting the socket lifecycle right first means that phase
adds message types, not infrastructure.
"""
from __future__ import annotations

import logging

from channels.generic.websocket import AsyncJsonWebsocketConsumer

logger = logging.getLogger("smartcafe.ws")

SYSTEM_GROUP = "system.status"


class SystemStatusConsumer(AsyncJsonWebsocketConsumer):
    """Broadcasts component health changes to authenticated dashboard clients."""

    groups = [SYSTEM_GROUP]

    async def connect(self) -> None:
        user = self.scope.get("user")
        if user is None or not user.is_authenticated:
            # 4401: application-level 'unauthenticated'. Browsers cannot read a
            # 401 on a websocket handshake, so the code carries the meaning.
            await self.close(code=4401)
            return
        await self.accept()
        await self.send_json({"type": "connection.established"})

    async def receive_json(self, content: dict, **kwargs) -> None:
        # The status socket is server-push only; a ping keeps intermediaries
        # from idling the connection out.
        if content.get("type") == "ping":
            await self.send_json({"type": "pong"})

    async def system_status(self, event: dict) -> None:
        await self.send_json({"type": "system.status", "payload": event.get("payload", {})})
