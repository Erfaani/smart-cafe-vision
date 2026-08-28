"""Public display WebSocket (Phase 7).

Unlike SystemStatusConsumer, this one is unauthenticated on purpose -- same
reasoning as PublicCafeView: a kiosk browser has no login and no token to
send. It never writes anything; every message it sends is read fresh from
apps/display/live.py or the database on each tick, and each connection polls
independently rather than fanning out from a shared broadcaster. There are
only ever a handful of kiosk connections per café -- one physical TV, not a
public multi-viewer service -- so the complexity of a pub/sub broadcaster
would buy nothing here; see docs/architecture.md for the fuller reasoning.

The café is re-fetched on every tick rather than cached for the connection's
lifetime: a kiosk connection is meant to run for hours or days, and an admin
changing `stay_color_stops` on the café settings page (Phase 6) must reach an
already-open display within one tick, not only on its next reconnect.
"""
from __future__ import annotations

import asyncio
import logging
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from apps.display.live import get_public_live_tracks, get_public_stats
from apps.display.models import DisplayMessage
from apps.tenants.models import Cafe

logger = logging.getLogger("smartcafe.ws")

TRACKS_INTERVAL_SECONDS = 1.0
STATS_INTERVAL_SECONDS = 10.0


class DisplayConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self) -> None:
        self.slug: str = self.scope["url_route"]["kwargs"]["slug"]
        query = parse_qs(self.scope.get("query_string", b"").decode())
        self.language_override: str | None = (query.get("lang") or [""])[0] or None

        cafe = await self._get_cafe()
        if cafe is None:
            # 4404: application-level 'no such café', mirroring the 4401
            # convention on SystemStatusConsumer -- a close code, because a
            # WebSocket handshake cannot carry an HTTP status body.
            await self.close(code=4404)
            return

        await self.accept()
        await self.send_json({"type": "connection.established"})
        await self._send_messages(cafe)
        self._tracks_task = asyncio.create_task(self._tracks_loop())
        self._stats_task = asyncio.create_task(self._stats_loop())

    async def disconnect(self, close_code: int) -> None:
        for task in (getattr(self, "_tracks_task", None), getattr(self, "_stats_task", None)):
            if task is not None:
                task.cancel()

    async def receive_json(self, content: dict, **kwargs) -> None:
        # Server-push only; a ping keeps intermediaries from idling a
        # long-lived kiosk connection out.
        if content.get("type") == "ping":
            await self.send_json({"type": "pong"})

    async def _tracks_loop(self) -> None:
        while True:
            cafe = await self._get_cafe()
            if cafe is None:
                await self.close(code=4404)
                return
            payload = await database_sync_to_async(get_public_live_tracks)(cafe)
            await self.send_json({"type": "display.tracks", "payload": payload})
            await asyncio.sleep(TRACKS_INTERVAL_SECONDS)

    async def _stats_loop(self) -> None:
        while True:
            cafe = await self._get_cafe()
            if cafe is None:
                return  # the tracks loop above will already be closing the socket
            payload = await database_sync_to_async(get_public_stats)(cafe)
            await self.send_json({"type": "display.stats", "payload": payload})
            await asyncio.sleep(STATS_INTERVAL_SECONDS)

    async def _send_messages(self, cafe: Cafe) -> None:
        language = self.language_override or cafe.default_language
        messages = await database_sync_to_async(_active_messages)(cafe, language)
        await self.send_json({"type": "display.messages", "payload": messages})

    async def _get_cafe(self) -> Cafe | None:
        return await database_sync_to_async(_get_active_cafe)(self.slug)


def _get_active_cafe(slug: str) -> Cafe | None:
    return Cafe.objects.filter(slug=slug, is_active=True).first()


def _active_messages(cafe: Cafe, language: str) -> list[dict]:
    return [
        {"id": str(message.id), "text": message.text(language)}
        for message in DisplayMessage.objects.filter(cafe=cafe, is_active=True)
    ]
