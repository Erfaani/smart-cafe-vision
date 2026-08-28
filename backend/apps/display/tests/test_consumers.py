"""DisplayConsumer tests, scoped to the consumer's own behaviour (connection
lifecycle, message types, café resolution) rather than re-testing
apps/display/live.py's computations, which have their own thorough coverage
in test_live.py.

Wrapped in a bare URLRouter, not the full ASGI `application` from
config.asgi: origin validation and JWT auth middleware are irrelevant to a
consumer that never reads scope['user'], and testing through them would
couple this test to unrelated infrastructure.
"""
from __future__ import annotations

import pytest
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator

from apps.display.models import DisplayMessage
from config.routing import websocket_urlpatterns

pytestmark = pytest.mark.django_db(transaction=True)

router = URLRouter(websocket_urlpatterns)


@pytest.mark.asyncio
async def test_connect_accepts_a_known_active_cafe(cafe):
    communicator = WebsocketCommunicator(router, f"/ws/display/{cafe.slug}/")
    connected, _ = await communicator.connect()
    assert connected
    await communicator.disconnect()


@pytest.mark.asyncio
async def test_connect_rejects_an_unknown_cafe():
    communicator = WebsocketCommunicator(router, "/ws/display/no-such-cafe/")
    connected, close_code = await communicator.connect()
    assert connected is False
    assert close_code == 4404


@pytest.mark.asyncio
async def test_connect_rejects_a_deactivated_cafe(cafe):
    cafe.is_active = False
    await _asave(cafe, ["is_active"])
    communicator = WebsocketCommunicator(router, f"/ws/display/{cafe.slug}/")
    connected, close_code = await communicator.connect()
    assert connected is False
    assert close_code == 4404


@pytest.mark.asyncio
async def test_first_messages_are_established_then_the_message_rotation(cafe):
    message = await _acreate_message(cafe, text_en="Hello")

    communicator = WebsocketCommunicator(router, f"/ws/display/{cafe.slug}/")
    await communicator.connect()

    assert await communicator.receive_json_from() == {"type": "connection.established"}
    second = await communicator.receive_json_from()
    assert second == {"type": "display.messages", "payload": [{"id": str(message.id), "text": "Hello"}]}

    await communicator.disconnect()


@pytest.mark.asyncio
async def test_tracks_and_stats_both_arrive_shortly_after_connecting(cafe):
    communicator = WebsocketCommunicator(router, f"/ws/display/{cafe.slug}/")
    await communicator.connect()
    await communicator.receive_json_from()  # connection.established
    await communicator.receive_json_from()  # display.messages

    seen_types = set()
    for _ in range(2):
        message = await communicator.receive_json_from(timeout=2)
        seen_types.add(message["type"])
        assert "payload" in message

    assert seen_types == {"display.tracks", "display.stats"}
    await communicator.disconnect()


@pytest.mark.asyncio
async def test_ping_gets_a_pong(cafe):
    communicator = WebsocketCommunicator(router, f"/ws/display/{cafe.slug}/")
    await communicator.connect()
    await communicator.receive_json_from()  # connection.established
    await communicator.receive_json_from()  # display.messages

    await communicator.send_json_to({"type": "ping"})
    # A tracks/stats push can legitimately interleave before the pong; drain
    # until it shows up rather than assuming it is the very next frame.
    for _ in range(5):
        message = await communicator.receive_json_from(timeout=2)
        if message["type"] == "pong":
            break
    else:
        pytest.fail("no pong received")

    await communicator.disconnect()


@pytest.mark.asyncio
async def test_messages_respect_the_lang_query_override(cafe):
    await _acreate_message(cafe, text_en="Hello", text_fa="سلام")

    communicator = WebsocketCommunicator(router, f"/ws/display/{cafe.slug}/?lang=fa")
    await communicator.connect()
    await communicator.receive_json_from()  # connection.established
    messages = await communicator.receive_json_from()

    assert messages["payload"][0]["text"] == "سلام"
    await communicator.disconnect()


# -- small async DB helpers (Channels' database_sync_to_async equivalent for
# fixture setup inside an async test) ---------------------------------------
async def _acreate_message(cafe, **kwargs) -> DisplayMessage:
    from channels.db import database_sync_to_async

    return await database_sync_to_async(DisplayMessage.objects.create)(cafe=cafe, **kwargs)


async def _asave(instance, fields: list[str]) -> None:
    from channels.db import database_sync_to_async

    await database_sync_to_async(instance.save)(update_fields=fields)
