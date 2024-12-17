"""Asynchronous Python client for Peblar EV chargers."""

from __future__ import annotations

import asyncio
import socket
from dataclasses import dataclass
from typing import Any, Self, TypeVar, cast

import backoff
import orjson
from aiohttp import ClientResponseError, CookieJar
from aiohttp.client import ClientError, ClientSession
from yarl import URL

from .exceptions import (
    PeblarAuthenticationError,
    PeblarConnectionError,
    PeblarConnectionTimeoutError,
    PeblarError,
)
from .models import (
    PeblarAvailableVersionsRequest,
    PeblarCurrentVersionsRequest,
    PeblarIdentifyRequest,
    PeblarLoginRequest,
    PeblarRequest,
    PeblarSystemInformation,
    PeblarSystemInformationRequest,
    PeblarUserConfiguration,
    PeblarUserConfigurationRequest,
    PeblarVersions,
)

_PeblarRequestT = TypeVar("_PeblarRequestT", bound=PeblarRequest[Any, Any])


@dataclass(kw_only=True)
class Peblar:
    """Main class for handling connections with a Peblar EV chargers."""

    host: str
    request_timeout: float = 8
    session: ClientSession | None = None

    _close_session: bool = False

    def __post_init__(self) -> None:
        """Initialize the Peblar object."""
        self.url = URL.build(scheme="http", host=self.host, path="/api/")

    @backoff.on_exception(
        backoff.expo,
        PeblarConnectionError,
        max_tries=3,
        logger=None,
    )
    async def request(
        self,
        request: _PeblarRequestT,
    ) -> _PeblarRequestT.response_type:  # type: ignore[name-defined]
        """Handle a request to a Peblar charger."""
        if self.session is None:
            self.session = ClientSession(
                cookie_jar=CookieJar(unsafe=True),
                json_serialize=orjson.dumps,  # type: ignore[arg-type]
            )
            self._close_session = True

        try:
            async with asyncio.timeout(self.request_timeout):
                response = await self.session.request(
                    request.request_method,
                    self.url.join(request.request_uri),
                    headers={"Content-Type": "application/json"},
                    data=request.to_json(),
                )
                response.raise_for_status()
        except TimeoutError as exception:
            msg = "Timeout occurred while connecting to the Peblar charger"
            raise PeblarConnectionTimeoutError(msg) from exception
        except ClientResponseError as exception:
            if exception.status == 401:
                msg = "Authentication error. Provided password is invalid."
                raise PeblarAuthenticationError(msg) from exception
            msg = "Error occurred while communicating to the Peblar charger"
            raise PeblarError(msg) from exception
        except (
            ClientError,
            socket.gaierror,
        ) as exception:
            msg = "Error occurred while communicating to the Peblar charger"
            raise PeblarConnectionError(msg) from exception

        if request.response_type is None:
            return None

        response_text = await response.text()
        return request.response_type.from_json(response_text)

    async def login(self, *, password: str) -> None:
        """Login into the Peblar charger."""
        await self.request(
            PeblarLoginRequest(
                password=password,
            )
        )

    async def available_versions(self) -> PeblarVersions:
        """Get available versions."""
        return cast(
            PeblarVersions, await self.request(PeblarAvailableVersionsRequest())
        )

    async def current_versions(self) -> PeblarVersions:
        """Get current versions."""
        return cast(PeblarVersions, await self.request(PeblarCurrentVersionsRequest()))

    async def identify(self) -> None:
        """Identify the Peblar charger."""
        await self.request(PeblarIdentifyRequest())

    async def system_information(self) -> PeblarSystemInformation:
        """Get information about the Peblar charger."""
        return cast(
            PeblarSystemInformation,
            await self.request(PeblarSystemInformationRequest()),
        )

    async def user_configuration(self) -> PeblarUserConfiguration:
        """Get information about the user configuration."""
        return cast(
            PeblarUserConfiguration,
            await self.request(PeblarUserConfigurationRequest()),
        )

    async def close(self) -> None:
        """Close open client session."""
        if self.session and self._close_session:
            await self.session.close()

    async def __aenter__(self) -> Self:
        """Async enter.

        Returns
        -------
            The Peblar object.

        """
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        """Async exit.

        Args:
        ----
            _exc_info: Exec type.

        """
        await self.close()
