"""Asynchronous Python client for Peblar EV chargers."""

from __future__ import annotations

import asyncio
import socket
from dataclasses import dataclass
from typing import Self

import backoff
import orjson
from aiohttp import ClientResponseError, CookieJar, hdrs
from aiohttp.client import ClientError, ClientSession
from yarl import URL

from .exceptions import (
    PeblarAuthenticationError,
    PeblarConnectionError,
    PeblarConnectionTimeoutError,
    PeblarError,
)
from .models import (
    BaseModel,
    PeblarApiToken,
    PeblarLogin,
    PeblarSystemInformation,
    PeblarUserConfiguration,
    PeblarVersions,
)


@dataclass(kw_only=True)
class Peblar:
    """Main class for handling connections with a Peblar EV chargers."""

    host: str
    request_timeout: float = 8
    session: ClientSession | None = None

    _close_session: bool = False

    def __post_init__(self) -> None:
        """Initialize the Peblar object."""
        self.url = URL.build(scheme="http", host=self.host, path="/api/v1/")

    @backoff.on_exception(
        backoff.expo,
        PeblarConnectionError,
        max_tries=3,
        logger=None,
    )
    async def request(
        self,
        uri: URL,
        *,
        method: str = hdrs.METH_GET,
        data: BaseModel | None = None,
    ) -> str:
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
                    method=method,
                    url=self.url.join(uri),
                    headers={"Content-Type": "application/json"},
                    data=data.to_json() if data else None,
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

        return await response.text()

    async def login(self, *, password: str) -> None:
        """Login into the Peblar charger."""
        await self.request(
            URL("auth/login"),
            method=hdrs.METH_POST,
            data=PeblarLogin(
                password=password,
            ),
        )

    async def api_token(self, *, generate_new_api_token: bool = False) -> str:
        """Get the API token."""
        url = URL("config/api-token")

        if generate_new_api_token:
            await self.request(url, method=hdrs.METH_POST)

        result = await self.request(url)
        return PeblarApiToken.from_json(result).api_token

    async def available_versions(self) -> PeblarVersions:
        """Get available versions."""
        result = await self.request(
            URL("system/software/automatic-update/available-versions")
        )
        return PeblarVersions.from_json(result)

    async def current_versions(self) -> PeblarVersions:
        """Get current versions."""
        result = await self.request(
            URL("system/software/automatic-update/current-versions")
        )
        return PeblarVersions.from_json(result)

    async def identify(self) -> None:
        """Identify the Peblar charger."""
        await self.request(URL("system/identify"), method=hdrs.METH_PUT)

    async def system_information(self) -> PeblarSystemInformation:
        """Get information about the Peblar charger."""
        result = await self.request(URL("system/info"))
        return PeblarSystemInformation.from_json(result)

    async def user_configuration(self) -> PeblarUserConfiguration:
        """Get information about the user configuration."""
        result = await self.request(URL("config/user"))
        return PeblarUserConfiguration.from_json(result)

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
