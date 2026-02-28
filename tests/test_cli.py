"""Tests for the Peblar CLI."""

from __future__ import annotations

import io
from contextlib import redirect_stdout

import pytest
from aresponses import ResponsesMockServer

from peblar.cli import identify, versions
from tests import load_fixture


def _add_versions_responses(aresponses: ResponsesMockServer) -> None:
    """Add aresponses mocks for the versions command."""
    aresponses.add(
        "example.com",
        "/api/v1/auth/login",
        "POST",
        aresponses.Response(status=200, body=load_fixture("ok_response.json")),
    )
    aresponses.add(
        "example.com",
        "/api/v1/system/software/automatic-update/current-versions",
        "GET",
        aresponses.Response(
            status=200,
            body=load_fixture("peblar_versions.json"),
        ),
    )
    aresponses.add(
        "example.com",
        "/api/v1/system/software/automatic-update/available-versions",
        "GET",
        aresponses.Response(
            status=200,
            body=load_fixture("peblar_versions.json"),
        ),
    )


def _add_identify_responses(aresponses: ResponsesMockServer) -> None:
    """Add aresponses mocks for the identify command."""
    aresponses.add(
        "example.com",
        "/api/v1/auth/login",
        "POST",
        aresponses.Response(status=200, body=load_fixture("ok_response.json")),
    )
    aresponses.add(
        "example.com",
        "/api/v1/system/identify",
        "PUT",
        aresponses.Response(status=200, body=load_fixture("ok_response.json")),
    )


@pytest.mark.asyncio
async def test_versions_quiet_option_suppresses_output(
    aresponses: ResponsesMockServer,
) -> None:
    """Test that --quiet option suppresses console output for versions command."""
    _add_versions_responses(aresponses)

    capture = io.StringIO()
    with redirect_stdout(capture):
        await versions(host="example.com", password="secret", quiet=True)

    assert capture.getvalue().strip() == ""


@pytest.mark.asyncio
async def test_versions_without_quiet_shows_output(
    aresponses: ResponsesMockServer,
) -> None:
    """Test that versions command shows output without --quiet option."""
    _add_versions_responses(aresponses)

    capture = io.StringIO()
    with redirect_stdout(capture):
        await versions(host="example.com", password="secret", quiet=False)

    output = capture.getvalue()
    assert "Peblar charger versions" in output
    assert "Firmware" in output
    assert "Customization" in output
    assert "1.6.1+1" in output


@pytest.mark.asyncio
async def test_versions_short_quiet_flag(
    aresponses: ResponsesMockServer,
) -> None:
    """Test that -q short flag suppresses output for versions command."""
    _add_versions_responses(aresponses)

    capture = io.StringIO()
    with redirect_stdout(capture):
        await versions(host="example.com", password="secret", quiet=True)

    assert capture.getvalue().strip() == ""


@pytest.mark.asyncio
async def test_identify_quiet_suppresses_output(
    aresponses: ResponsesMockServer,
) -> None:
    """Test that --quiet suppresses output for identify command."""
    _add_identify_responses(aresponses)

    capture = io.StringIO()
    with redirect_stdout(capture):
        await identify(host="example.com", password="secret", quiet=True)

    assert capture.getvalue().strip() == ""


@pytest.mark.asyncio
async def test_identify_without_quiet_shows_success(
    aresponses: ResponsesMockServer,
) -> None:
    """Test that identify command shows success without --quiet option."""
    _add_identify_responses(aresponses)

    capture = io.StringIO()
    with redirect_stdout(capture):
        await identify(host="example.com", password="secret", quiet=False)

    assert "Success" in capture.getvalue()
