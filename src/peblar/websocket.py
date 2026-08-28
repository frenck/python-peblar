"""Asynchronous Python client for Peblar EV chargers."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Self

from aiohttp import ClientError, WSMsgType
from yarl import URL

from .const import WebsocketTopic
from .exceptions import (
    PeblarConnectionError,
    PeblarConnectionTimeoutError,
    PeblarError,
)
from .models import PeblarSessionStatus, PeblarTokenFound

if TYPE_CHECKING:
    from aiohttp import ClientSession, ClientWebSocketResponse

EventCallback = Callable[[dict[str, Any]], None]


def session_status_topic(connector: int = 1) -> str:
    """Return the session status topic for a connector."""
    return f"/session/status/connector/{connector}"


@dataclass(kw_only=True)
class PeblarWebsocket:
    """Live event stream from a Peblar charger.

    The charger pushes changes instead of making you poll for them, which
    also keeps you clear of the API's rate limit. It authenticates with the
    same session cookie as the web API, so this is handed out by
    Peblar.websocket() once you are logged in.

    Subscriptions survive nothing: if the connection drops, resubscribe
    after reconnecting.
    """

    host: str
    session: ClientSession
    request_timeout: float = 8

    _client: ClientWebSocketResponse | None = field(default=None, init=False)
    _callbacks: dict[str, EventCallback] = field(default_factory=dict, init=False)
    _pending: dict[str, asyncio.Future[None]] = field(default_factory=dict, init=False)
    _reader: asyncio.Task[None] | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        """Initialize the websocket object."""
        self.url = URL.build(scheme="ws", host=self.host, path="/api/v1/ws")

    @property
    def connected(self) -> bool:
        """Return whether the websocket is up and dispatching events.

        A reader that has stopped means nothing reaches the callbacks any
        more, so an open socket on its own does not count as connected.
        """
        return (
            self._client is not None
            and not self._client.closed
            and self._reader is not None
            and not self._reader.done()
        )

    async def connect(self) -> None:
        """Open the websocket connection to the charger."""
        if self.connected:
            return

        try:
            self._client = await self.session.ws_connect(self.url)
        except TimeoutError as exception:
            msg = "Timeout occurred while connecting to the Peblar charger websocket"
            raise PeblarConnectionTimeoutError(msg) from exception
        except (ClientError, OSError, RuntimeError) as exception:
            msg = "Error occurred while connecting to the Peblar charger websocket"
            raise PeblarConnectionError(msg) from exception

        self._reader = asyncio.create_task(self._read_messages())

    async def subscribe(self, topic: str, callback: EventCallback) -> None:
        """Subscribe to a topic, handing every event to the callback.

        The callback receives the event payload, normalised to a mapping:
        a topic that sends anything else, null included, arrives as an
        empty dict. For the topics with a known shape, prefer the typed
        helpers below.

        Keep the callback from raising. One reader serves every
        subscription on the connection, so an exception escaping a
        callback stops all of them; listen() re-raises it and connected
        turns False, but the connection is gone either way.
        """
        # Registered before subscribing, not after: the charger pushes the
        # current state immediately behind the acknowledgement, and that
        # first event lands while we are still waiting on the ack.
        self._callbacks[topic] = callback
        try:
            await self._send_action("subscribe", topic)
        except PeblarError:
            self._callbacks.pop(topic, None)
            raise

    async def subscribe_session_status(
        self,
        callback: Callable[[PeblarSessionStatus], None],
        *,
        connector: int = 1,
    ) -> None:
        """Subscribe to charging session updates for a connector.

        The charger sends the current status right after subscribing, so
        the callback fires once without anything having changed.
        """
        await self.subscribe(
            session_status_topic(connector),
            lambda data: callback(PeblarSessionStatus.from_dict(data)),
        )

    async def subscribe_token_found(
        self,
        callback: Callable[[PeblarTokenFound], None],
        *,
        topic: WebsocketTopic = WebsocketTopic.RFID_TOKEN_FOUND,
    ) -> None:
        """Subscribe to tokens being presented to the charger."""
        await self.subscribe(
            topic,
            lambda data: callback(PeblarTokenFound.from_dict(data)),
        )

    async def unsubscribe(self, topic: str) -> None:
        """Unsubscribe from a topic."""
        await self._send_action("unsubscribe", topic)
        self._callbacks.pop(topic, None)

    async def listen(self) -> None:
        """Block until the connection closes.

        Raises whatever knocked the connection over, so a caller can treat
        this as the lifetime of the connection and reconnect when it ends.

        Listening is observing, not owning: cancelling this leaves the
        connection up and events still flowing to their callbacks. Call
        disconnect() to actually tear it down.
        """
        if self._reader is None:
            msg = "Not connected to the Peblar charger websocket"
            raise PeblarError(msg)

        await asyncio.shield(self._reader)

    async def disconnect(self) -> None:
        """Close the websocket connection."""
        if self._reader is not None:
            self._reader.cancel()
            # The reader owns the socket, so let it finish unwinding
            # first. Whatever it died of is reported by listen(), never by
            # teardown, which has to stay safe to call from a finally.
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._reader
            self._reader = None

        if self._client is not None:
            # Teardown is called from finally blocks; it does not get to
            # raise on the way out.
            with contextlib.suppress(Exception):
                await self._client.close()
            self._client = None

        self._callbacks.clear()
        self._pending.clear()

    async def _send_action(self, action: str, topic: str) -> None:
        """Send a subscribe or unsubscribe request and wait for the result."""
        if self._client is None or not self.connected:
            msg = "Not connected to the Peblar charger websocket"
            raise PeblarError(msg)

        if topic in self._pending:
            msg = f"A request for topic {topic} is already in flight"
            raise PeblarError(msg)

        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._pending[topic] = future

        try:
            await self._client.send_json({"action": action, "topic": topic})
            async with asyncio.timeout(self.request_timeout):
                await future
        except TimeoutError as exception:
            msg = f"Timeout on the {action} request for topic {topic}"
            raise PeblarConnectionTimeoutError(msg) from exception
        except (ClientError, OSError, RuntimeError) as exception:
            msg = f"Error occurred during the {action} request for topic {topic}"
            raise PeblarConnectionError(msg) from exception
        finally:
            self._pending.pop(topic, None)

    async def _read_messages(self) -> None:
        """Dispatch incoming messages until the connection closes."""
        if self._client is None:
            return

        cancelled = False
        try:
            async for message in self._client:
                if message.type is not WSMsgType.TEXT:
                    continue

                # Anything unparsable is skipped rather than allowed to
                # kill the reader, which would silently stop every
                # subscription on this connection.
                try:
                    payload = message.json()
                except ValueError:
                    continue

                self._handle_message(payload)
        except asyncio.CancelledError:
            cancelled = True
            raise
        finally:
            # The reader owns the socket. If it stops on its own then
            # nothing is consuming frames any more, so the connection goes
            # with it rather than lingering open with no reader. On
            # cancellation disconnect() is already doing the closing.
            if not cancelled and not self._client.closed:
                # Never let a failing close replace whatever stopped the
                # reader, since that is the error listen() reports.
                with contextlib.suppress(Exception):
                    await self._client.close()

            self._callbacks.clear()

            # Nobody is going to answer a pending subscribe any more.
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(
                        PeblarConnectionError(
                            "Peblar charger websocket closed while waiting for a result"
                        )
                    )

    def _handle_message(self, message: Any) -> None:
        """Route a single message to a pending request or a subscriber.

        Nothing in here trusts the shape of what arrived. A surprising
        payload gets dropped, because raising would end the reader task
        and take every subscription down with it.
        """
        if not isinstance(message, dict):
            return

        topic = message.get("topic")
        if not topic:
            return

        data = message.get("data")
        if not isinstance(data, dict):
            data = {}

        if message.get("type") == "result":
            if (future := self._pending.get(topic)) and not future.done():
                if data.get("status") == "ok":
                    future.set_result(None)
                else:
                    reason = data.get("message", "no reason given")
                    future.set_exception(
                        PeblarError(f"Peblar charger rejected topic {topic}: {reason}")
                    )
            return

        if message.get("type") == "event" and (callback := self._callbacks.get(topic)):
            callback(data)

    async def __aenter__(self) -> Self:
        """Async enter.

        Returns
        -------
            The connected PeblarWebsocket object.

        """
        await self.connect()
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        """Async exit.

        Args:
        ----
            _exc_info: Exec type.

        """
        await self.disconnect()
