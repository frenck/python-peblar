"""Asynchronous Python client for Peblar EV chargers."""

from __future__ import annotations

import asyncio

import pytest
from aiohttp import ClientResponse, ClientSession
from aresponses import Response, ResponsesMockServer

from peblar import Peblar
from peblar.exceptions import (
    PeblarAuthenticationError,
    PeblarConnectionError,
    PeblarError,
)


async def test_identify(aresponses: ResponsesMockServer) -> None:
    """Test the identify method."""

    async def response_handler(request: ClientResponse) -> Response:
        """Response handler for this test."""
        assert not await request.text()
        return aresponses.Response(status=200)

    aresponses.add(
        "example.com",
        "/api/v1/system/identify",
        "PUT",
        response_handler,
    )
    async with Peblar(host="example.com") as peblar:
        await peblar.identify()


async def test_request_with_shared_session(aresponses: ResponsesMockServer) -> None:
    """Test a passed in shared session works as expected."""
    aresponses.add(
        "example.com",
        "/api/v1/system/identify",
        "PUT",
        aresponses.Response(status=200),
    )
    async with ClientSession() as session:
        peblar = Peblar(host="example.com", session=session)
        await peblar.identify()
        await peblar.close()


async def test_http_error400(aresponses: ResponsesMockServer) -> None:
    """Test HTTP 404 response handling."""
    aresponses.add(
        "example.com",
        "/api/v1/system/identify",
        "PUT",
        aresponses.Response(text="OMG PUPPIES!", status=400),
    )

    async with Peblar(host="example.com") as peblar:
        with pytest.raises(PeblarError):
            await peblar.identify()


async def test_unauthenticated_response(aresponses: ResponsesMockServer) -> None:
    """Test authentication failure."""
    aresponses.add(
        "example.com",
        "/api/v1/system/identify",
        "PUT",
        aresponses.Response(status=401),
    )

    async with Peblar(host="example.com") as peblar:
        with pytest.raises(PeblarAuthenticationError):
            await peblar.identify()
