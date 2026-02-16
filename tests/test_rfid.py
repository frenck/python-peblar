"""Tests for RFID token operations."""

from __future__ import annotations

import orjson
from aiohttp import ClientResponse
from aresponses import Response, ResponsesMockServer
from yarl import URL

from peblar import Peblar
from tests import load_fixture


async def test_rfid_tokens(aresponses: ResponsesMockServer) -> None:
    """Test fetching the list of RFID tokens."""
    aresponses.add(
        "example.com",
        "/api/v1/auth/login",
        "POST",
        aresponses.Response(status=200),
    )
    aresponses.add(
        "example.com",
        "/api/v1/config/auth/standalonelist",
        "GET",
        aresponses.Response(
            status=200,
            body=load_fixture("standalonelist.json"),
        ),
    )

    async with Peblar(host="example.com") as peblar:
        await peblar.login(password="secret")
        tokens = await peblar.rfid_tokens()

    assert len(tokens) == 2
    assert tokens[0].rfid_token_uid == "0123456789ABCD"  # noqa: S105
    assert tokens[0].rfid_token_description == "My RFID Card"  # noqa: S105
    assert tokens[1].rfid_token_uid == "0123456789ABCE"  # noqa: S105
    assert tokens[1].rfid_token_description == "My Other RFID Card"  # noqa: S105


async def test_add_rfid_token(aresponses: ResponsesMockServer) -> None:
    """Test adding an RFID token."""
    uid = "0123456789ABCD"
    description = "My Charge Card"

    async def response_handler(request: ClientResponse) -> Response:
        """Assert the add RFID token payload."""
        assert orjson.loads(await request.text()) == {
            "RfidTokenUid": uid,
            "RfidTokenDescription": description,
        }
        return aresponses.Response(status=200)

    aresponses.add(
        "example.com",
        "/api/v1/auth/login",
        "POST",
        aresponses.Response(status=200),
    )
    aresponses.add(
        "example.com",
        "/api/v1/config/auth/standalonelist",
        "POST",
        response_handler,
    )

    async with Peblar(host="example.com") as peblar:
        await peblar.login(password="secret")
        await peblar.add_rfid_token(
            rfid_token_uid=uid,
            rfid_token_description=description,
        )


async def test_delete_rfid_token(aresponses: ResponsesMockServer) -> None:
    """Test deleting an RFID token."""
    uid = "0123456789ABCD"
    path = URL("config/auth/standalonelist") / uid

    aresponses.add(
        "example.com",
        "/api/v1/auth/login",
        "POST",
        aresponses.Response(status=200),
    )
    aresponses.add(
        "example.com",
        f"/api/v1/{path}",
        "DELETE",
        aresponses.Response(status=200),
    )

    async with Peblar(host="example.com") as peblar:
        await peblar.login(password="secret")
        await peblar.delete_rfid_token(uid=uid)
