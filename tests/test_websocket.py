"""Tests for `peblar.websocket`."""

# pylint: disable=redefined-outer-name
from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any

import pytest
from aiohttp import ClientError, ClientSession, WSMsgType, web
from aiohttp.test_utils import TestServer
from yarl import URL

from peblar.const import SessionState, WebsocketTopic
from peblar.exceptions import (
    PeblarConnectionError,
    PeblarConnectionTimeoutError,
    PeblarError,
)
from peblar.models import PeblarFirmwareUpdateStatus
from peblar.websocket import PeblarWebsocket, session_status_topic

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from peblar.models import PeblarSessionStatus, PeblarTokenFound

SESSION_TOPIC = session_status_topic()
REJECTED_TOPIC = "/nope"
SILENT_TOPIC = "/silent"
BINARY_TOPIC = "/binary"
GARBAGE_TOPIC = "/garbage"
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

        if action == "subscribe" and topic == GARBAGE_TOPIC:
            # Not JSON at all, then valid JSON that is not an object, then
            # a well formed message whose data is null.
            await websocket.send_str("}{ not json")
            await websocket.send_str("[1, 2, 3]")
            await websocket.send_json(
                {"topic": GARBAGE_TOPIC, "type": "event", "data": None}
            )

        # The real charger pushes current state right behind the ack.
        if action == "subscribe" and topic == SESSION_TOPIC:
            await websocket.send_json(
                {"topic": topic, "type": "event", "data": SESSION_EVENT}
            )
        if action == "subscribe" and topic == WebsocketTopic.FIRMWARE_UPDATE_STATUS:
            await websocket.send_json(
                {
                    "topic": topic,
                    "type": "event",
                    "data": {
                        "status": "EFwUpdateSuccess",
                        "fwIdentOld": "1.9.1+1+WL-1",
                        "fwIdentNew": "1.9.2+1+WL-1",
                    },
                }
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
    with pytest.raises(
        PeblarConnectionTimeoutError, match="Timeout on the subscribe request"
    ):
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
    with pytest.raises(
        PeblarConnectionError, match="Error occurred during the subscribe request"
    ):
        await websocket.subscribe(SESSION_TOPIC, lambda _: None)


async def test_async_context_manager(websocket: PeblarWebsocket) -> None:
    """Test the websocket connects and disconnects as a context manager."""
    async with websocket as connected:
        assert connected.connected is True
    assert websocket.connected is False


async def test_malformed_frames_do_not_kill_the_reader(
    websocket: PeblarWebsocket,
) -> None:
    """Test junk on the wire is skipped rather than ending every subscription.

    The reader task serves every subscription on the connection, so an
    exception in it would silently stop all of them.
    """
    received: list[dict[str, Any]] = []
    await websocket.connect()
    await websocket.subscribe(GARBAGE_TOPIC, received.append)
    await asyncio.sleep(0.05)

    # Still alive, and the null data arrived normalised to an empty dict.
    assert websocket.connected is True
    assert received == [{}]

    # And the connection still works afterwards.
    await websocket.subscribe_session_status(lambda _: None)


async def test_one_in_flight_request_per_topic(
    websocket: PeblarWebsocket,
) -> None:
    """Test a second request for a topic cannot orphan the first one.

    Both used to write into the same pending slot, so one caller would
    wait forever for a result that had already been handed to the other.
    """
    await websocket.connect()
    websocket.request_timeout = 5

    first = asyncio.create_task(websocket.subscribe(SILENT_TOPIC, lambda _: None))
    await asyncio.sleep(0.05)

    with pytest.raises(PeblarError, match="already in flight"):
        await websocket.subscribe(SILENT_TOPIC, lambda _: None)

    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first


async def test_a_raising_callback_is_visible_not_silent(
    websocket: PeblarWebsocket,
) -> None:
    """Test a callback that raises does not leave a zombie connection.

    One reader serves every subscription, so a raising callback stops
    them all. That has to be observable rather than leaving `connected`
    claiming everything is fine.
    """
    await websocket.connect()

    def boom(_data: dict[str, Any]) -> None:
        msg = "consumer bug"
        raise RuntimeError(msg)

    await websocket.subscribe_session_status(lambda _: boom({}))
    await asyncio.sleep(0.05)

    assert websocket.connected is False
    with pytest.raises(RuntimeError, match="consumer bug"):
        await websocket.listen()


async def test_disconnect_never_raises(websocket: PeblarWebsocket) -> None:
    """Test teardown stays safe even when the reader died of something.

    disconnect() gets called from `finally` blocks and context manager
    exits, so it must not resurrect whatever killed the reader.
    """
    await websocket.connect()

    def boom(_data: dict[str, Any]) -> None:
        msg = "consumer bug"
        raise RuntimeError(msg)

    await websocket.subscribe_session_status(lambda _: boom({}))
    await asyncio.sleep(0.05)

    await websocket.disconnect()
    assert websocket.connected is False


async def test_context_manager_exit_survives_a_dead_reader(
    websocket: PeblarWebsocket,
) -> None:
    """Test `async with` unwinds cleanly after a callback blew up."""

    def boom(_data: dict[str, Any]) -> None:
        msg = "consumer bug"
        raise RuntimeError(msg)

    async with websocket as connected:
        await connected.subscribe_session_status(lambda _: boom({}))
        await asyncio.sleep(0.05)

    assert websocket.connected is False


async def test_reader_closes_the_socket_when_it_stops(
    websocket: PeblarWebsocket,
) -> None:
    """Test a stopped reader does not leave the socket open behind it.

    The reader owns the socket, so if it goes the connection goes too
    rather than lingering with nothing consuming frames.
    """
    await websocket.connect()

    def boom(_data: dict[str, Any]) -> None:
        msg = "consumer bug"
        raise RuntimeError(msg)

    await websocket.subscribe_session_status(lambda _: boom({}))

    # Wait for the reader to finish unwinding rather than racing it.
    with pytest.raises(RuntimeError, match="consumer bug"):
        await websocket.listen()

    client = websocket._client  # pylint: disable=protected-access
    assert client is not None
    assert client.closed is True
    # Subscriptions went with it.
    assert not websocket._callbacks  # pylint: disable=protected-access


async def test_cancelling_listen_leaves_the_socket_open(
    websocket: PeblarWebsocket,
) -> None:
    """Test cancelling the observer does not close what it was watching."""
    await websocket.connect()
    listener = asyncio.create_task(websocket.listen())
    await asyncio.sleep(0)
    listener.cancel()
    with pytest.raises(asyncio.CancelledError):
        await listener

    client = websocket._client  # pylint: disable=protected-access
    assert client is not None
    assert client.closed is False
    assert websocket.connected is True


async def test_connect_to_a_closed_session(websocket: PeblarWebsocket) -> None:
    """Test a closed session surfaces as a connection error.

    aiohttp raises RuntimeError there rather than a ClientError, so it
    used to escape as an unexpected exception type.
    """
    await websocket.session.close()
    with pytest.raises(PeblarConnectionError, match="Error occurred"):
        await websocket.connect()


async def test_a_failing_close_does_not_mask_the_real_error(
    websocket: PeblarWebsocket,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test a broken close cannot replace what actually stopped the reader.

    listen() reports the cause, so a teardown failure must not overwrite
    it on the way out.
    """
    await websocket.connect()

    async def failing_close(*_args: Any, **_kwargs: Any) -> None:
        msg = "close blew up"
        raise RuntimeError(msg)

    def boom(_data: dict[str, Any]) -> None:
        msg = "consumer bug"
        raise RuntimeError(msg)

    client = websocket._client  # pylint: disable=protected-access
    assert client is not None
    monkeypatch.setattr(client, "close", failing_close)

    await websocket.subscribe_session_status(lambda _: boom({}))

    # The consumer bug, not the close failure.
    with pytest.raises(RuntimeError, match="consumer bug"):
        await websocket.listen()

    # And teardown still does not raise.
    await websocket.disconnect()


async def test_disconnect_clears_in_flight_bookkeeping(
    websocket: PeblarWebsocket,
) -> None:
    """Test a reconnect is not blocked by the previous connection.

    The in-flight guard rejects a second request for a topic, so a
    disconnect during an unanswered request has to drop that bookkeeping
    or the first request after reconnecting is refused on behalf of a
    connection that no longer exists.
    """
    await websocket.connect()

    pending = asyncio.create_task(websocket.subscribe(SILENT_TOPIC, lambda _: None))
    await asyncio.sleep(0.05)
    assert websocket._pending  # pylint: disable=protected-access

    await websocket.disconnect()
    pending.cancel()
    with contextlib.suppress(asyncio.CancelledError, PeblarError):
        await pending

    assert not websocket._pending  # pylint: disable=protected-access

    # Reconnecting and asking for the same topic again is fine.
    await websocket.connect()
    await websocket.subscribe_session_status(lambda _: None)


async def test_disconnect_ends_listen_cleanly(websocket: PeblarWebsocket) -> None:
    """Test asking for a shutdown is not reported as a failure.

    A caller awaiting listen() in its own task was never cancelled, so
    handing it a CancelledError because someone else called disconnect()
    would make it look like it was.
    """
    await websocket.connect()
    listener = asyncio.create_task(websocket.listen())
    await asyncio.sleep(0.05)

    await websocket.disconnect()
    await listener  # returns, does not raise

    assert websocket.connected is False


async def test_cancelling_listen_still_cancels_the_caller(
    websocket: PeblarWebsocket,
) -> None:
    """Test a cancellation aimed at listen() is still delivered."""
    await websocket.connect()
    listener = asyncio.create_task(websocket.listen())
    await asyncio.sleep(0.05)

    listener.cancel()
    with pytest.raises(asyncio.CancelledError):
        await listener

    # The connection is untouched, listening is only observing.
    assert websocket.connected is True


async def test_subscribe_firmware_update_status(websocket: PeblarWebsocket) -> None:
    """Test firmware update progress events are parsed.

    The charger replays the result of the last update on subscribe, so
    this arrives without an update having been triggered.
    """
    received: list[PeblarFirmwareUpdateStatus] = []
    arrived = asyncio.Event()

    def collect(status: PeblarFirmwareUpdateStatus) -> None:
        received.append(status)
        arrived.set()

    await websocket.connect()
    await websocket.subscribe_firmware_update_status(collect)

    async with asyncio.timeout(5):
        await arrived.wait()

    assert received[0].status == "EFwUpdateSuccess"
    assert received[0].firmware_old == "1.9.1+1+WL-1"
    assert received[0].firmware_new == "1.9.2+1+WL-1"


def test_firmware_update_status_version_fields_are_optional() -> None:
    """Test a status without version identifiers still parses."""
    status = PeblarFirmwareUpdateStatus.from_dict({"status": "Unknown"})
    assert status.firmware_old == ""
    assert status.firmware_new == ""
