"""Tests for `peblar.websocket`."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest
from aiohttp import ClientError, ClientSession, WSMsgType, web
from aiohttp.test_utils import TestServer
from yarl import URL

from peblar.const import SessionState, WebsocketTopic
from peblar.exceptions import PeblarConnectionError, PeblarError
from peblar.websocket import PeblarWebsocket, session_status_topic

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from peblar.models import PeblarSessionStatus, PeblarTokenFound

SESSION_TOPIC = session_status_topic()
REJECTED_TOPIC = "/nope"
SILENT_TOPIC = "/silent"
BINARY_TOPIC = "/binary"
SESSION_EVENT = {
    "meterData": {
        "instantaneousPower": [3450, 3410, 3480],
        "sessionEnergy": 13104,
        "totalEnergy": 6529794,
    },
    "state": "charging",
}


async def peblar_ws_handler(request: web.Request) -> web.WebSocketResponse:
    """Stand in for the charger's websocket, speaking its protocol."""
    websocket = web.WebSocketResponse()
    await websocket.prepare(request)

    async for message in websocket:
        if message.type is not WSMsgType.TEXT:
            continue

        payload = message.json()
        action, topic = payload["action"], payload["topic"]

        if topic == SILENT_TOPIC:
            continue

        if topic == REJECTED_TOPIC:
            await websocket.send_json(
                {
                    "topic": topic,
                    "type": "result",
                    "data": {
                        "action": action,
                        "status": "error",
                        "message": "Unknown topic",
                    },
                }
            )
            continue

        await websocket.send_json(
            {
                "topic": topic,
                "type": "result",
                "data": {"action": action, "status": "ok", "message": "ok"},
            }
        )

        if action == "subscribe" and topic == BINARY_TOPIC:
            await websocket.send_bytes(b"not text")

        # The real charger pushes current state right behind the ack.
        if action == "subscribe" and topic == SESSION_TOPIC:
            await websocket.send_json(
                {"topic": topic, "type": "event", "data": SESSION_EVENT}
            )
        if action == "subscribe" and topic == WebsocketTopic.RFID_TOKEN_FOUND:
            await websocket.send_json(
                {
                    "topic": topic,
                    "type": "event",
                    "data": {"tokenId": "0123456789ABCD"},
                }
            )

    return websocket


@pytest.fixture
async def websocket() -> AsyncGenerator[PeblarWebsocket, None]:
    """Return a PeblarWebsocket pointed at an in-process charger stand-in."""
    app = web.Application()
    app.router.add_get("/api/v1/ws", peblar_ws_handler)
    server = TestServer(app)
    await server.start_server()

    async with ClientSession() as session:
        client = PeblarWebsocket(host="example.com", session=session)
        # The stand-in listens on an ephemeral port, so aim at it directly.
        client.url = URL(f"ws://{server.host}:{server.port}/api/v1/ws")
        yield client
        await client.disconnect()

    await server.close()


async def test_connect_and_disconnect(websocket: PeblarWebsocket) -> None:
    """Test the connection reports its own state."""
    assert websocket.connected is False
    await websocket.connect()
    assert websocket.connected is True
    await websocket.disconnect()
    assert websocket.connected is False


async def test_connect_is_idempotent(websocket: PeblarWebsocket) -> None:
    """Test connecting twice keeps the existing connection."""
    await websocket.connect()
    client = websocket._client  # pylint: disable=protected-access
    await websocket.connect()
    assert websocket._client is client  # pylint: disable=protected-access


async def test_subscribe_receives_initial_state(websocket: PeblarWebsocket) -> None:
    """Test the state pushed right behind the ack is not dropped."""
    received: list[PeblarSessionStatus] = []
    arrived = asyncio.Event()

    def collect(status: PeblarSessionStatus) -> None:
        received.append(status)
        arrived.set()

    await websocket.connect()
    await websocket.subscribe_session_status(collect)

    async with asyncio.timeout(5):
        await arrived.wait()

    status = received[0]
    assert status.state is SessionState.CHARGING
    assert status.meter_data is not None
    assert status.meter_data.session_energy == 13104
    assert status.meter_data.instantaneous_power_total == 10340


async def test_subscribe_token_found(websocket: PeblarWebsocket) -> None:
    """Test RFID token events are parsed."""
    received: list[PeblarTokenFound] = []
    arrived = asyncio.Event()

    def collect(token: PeblarTokenFound) -> None:
        received.append(token)
        arrived.set()

    await websocket.connect()
    await websocket.subscribe_token_found(collect)

    async with asyncio.timeout(5):
        await arrived.wait()

    assert received[0].token_id == "0123456789ABCD"


async def test_subscribe_raw_topic(websocket: PeblarWebsocket) -> None:
    """Test a raw subscription hands the payload through untouched."""
    await websocket.connect()
    await websocket.subscribe(WebsocketTopic.STATUS_CHANGED, lambda _: None)
    # pylint: disable-next=protected-access
    assert WebsocketTopic.STATUS_CHANGED in websocket._callbacks


async def test_subscribe_rejected(websocket: PeblarWebsocket) -> None:
    """Test a topic the charger refuses raises and leaves no callback behind."""
    await websocket.connect()
    with pytest.raises(PeblarError, match="Unknown topic"):
        await websocket.subscribe(REJECTED_TOPIC, lambda _: None)
    # pylint: disable-next=protected-access
    assert REJECTED_TOPIC not in websocket._callbacks


async def test_unsubscribe_stops_callbacks(websocket: PeblarWebsocket) -> None:
    """Test unsubscribing drops the callback."""
    await websocket.connect()
    await websocket.subscribe_session_status(lambda _: None)
    await websocket.unsubscribe(SESSION_TOPIC)
    # pylint: disable-next=protected-access
    assert SESSION_TOPIC not in websocket._callbacks


async def test_subscribe_without_connection(websocket: PeblarWebsocket) -> None:
    """Test subscribing before connecting is refused."""
    with pytest.raises(PeblarError, match="Not connected"):
        await websocket.subscribe(SESSION_TOPIC, lambda _: None)


async def test_listen_without_connection(websocket: PeblarWebsocket) -> None:
    """Test listening before connecting is refused."""
    with pytest.raises(PeblarError, match="Not connected"):
        await websocket.listen()


async def test_listen_returns_when_server_closes(
    websocket: PeblarWebsocket,
) -> None:
    """Test listen returns once the charger hangs up."""
    await websocket.connect()
    await websocket.subscribe_session_status(lambda _: None)

    client = websocket._client  # pylint: disable=protected-access
    assert client is not None
    await client.close()

    async with asyncio.timeout(5):
        await websocket.listen()

    assert websocket.connected is False


async def test_cancelling_listen_keeps_the_connection(
    websocket: PeblarWebsocket,
) -> None:
    """Test listening is observing, not owning."""
    await websocket.connect()
    listener = asyncio.create_task(websocket.listen())
    await asyncio.sleep(0)
    listener.cancel()
    with pytest.raises(asyncio.CancelledError):
        await listener

    assert websocket.connected is True
    # The reader survived, so the charger still answers.
    await websocket.subscribe_session_status(lambda _: None)


async def test_connect_failure() -> None:
    """Test an unreachable charger surfaces as a connection error."""
    async with ClientSession() as session:
        client = PeblarWebsocket(host="example.com", session=session)
        # Port 1 on localhost has nothing listening.
        client.url = URL("ws://127.0.0.1:1/api/v1/ws")
        with pytest.raises(PeblarConnectionError, match="Error occurred"):
            await client.connect()


async def test_unknown_messages_are_ignored(websocket: PeblarWebsocket) -> None:
    """Test malformed or unknown messages do not take the reader down."""
    await websocket.connect()
    # pylint: disable-next=protected-access
    handle: Any = websocket._handle_message
    handle({})
    handle({"topic": "/unknown", "type": "event", "data": {}})
    handle({"topic": SESSION_TOPIC, "type": "bogus", "data": {}})
    assert websocket.connected is True


async def test_subscribe_times_out(websocket: PeblarWebsocket) -> None:
    """Test a charger that never acknowledges surfaces as a timeout."""
    websocket.request_timeout = 0.1
    await websocket.connect()
    with pytest.raises(PeblarConnectionError, match="Timeout while trying"):
        await websocket.subscribe(SILENT_TOPIC, lambda _: None)


async def test_pending_subscribe_fails_when_connection_drops(
    websocket: PeblarWebsocket,
) -> None:
    """Test an unanswered subscribe gives up when the charger hangs up."""
    await websocket.connect()
    pending = asyncio.create_task(websocket.subscribe(SILENT_TOPIC, lambda _: None))
    await asyncio.sleep(0.05)

    client = websocket._client  # pylint: disable=protected-access
    assert client is not None
    await client.close()

    with pytest.raises(PeblarConnectionError, match="closed while waiting"):
        await pending


async def test_non_text_frames_are_skipped(websocket: PeblarWebsocket) -> None:
    """Test a binary frame does not take the reader down."""
    await websocket.connect()
    await websocket.subscribe(BINARY_TOPIC, lambda _: None)
    await asyncio.sleep(0.05)
    assert websocket.connected is True


async def test_send_failure_surfaces_as_connection_error(
    websocket: PeblarWebsocket,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test a failing send is reported as a connection error."""
    await websocket.connect()

    async def boom(*_args: Any, **_kwargs: Any) -> None:
        raise ClientError

    # pylint: disable-next=protected-access
    monkeypatch.setattr(websocket._client, "send_json", boom)
    with pytest.raises(PeblarConnectionError, match="Error occurred while trying"):
        await websocket.subscribe(SESSION_TOPIC, lambda _: None)


async def test_async_context_manager(websocket: PeblarWebsocket) -> None:
    """Test the websocket connects and disconnects as a context manager."""
    async with websocket as connected:
        assert connected.connected is True
    assert websocket.connected is False
