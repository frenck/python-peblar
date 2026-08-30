"""Tests for the meterhistory CLI command."""

from __future__ import annotations

import io
import re
from contextlib import redirect_stdout
from datetime import UTC, datetime
from pathlib import Path  # noqa: TC003

import pytest
import typer
from aioresponses import aioresponses

from peblar import Peblar
from peblar.cli import meterhistory, normalize_meterhistory_bound
from tests import load_fixture

HOST = "example.com"
BASE_URL = f"http://{HOST}/api/v1/"
LOGIN_URL = BASE_URL + "auth/login"
METERHISTORY_URL = BASE_URL + "statistics/meterhistory"
STANDALONELIST_URL = BASE_URL + "config/auth/standalonelist"


def _add_meterhistory_responses(
    mocked: aioresponses,
    *,
    meterhistory_fixture: str,
) -> None:
    """Register HTTP mocks for login, meter history, and RFID token list."""
    mocked.post(LOGIN_URL, status=200, body="", content_type="text/plain")
    mocked.get(
        METERHISTORY_URL,
        status=200,
        body=load_fixture(meterhistory_fixture),
    )
    mocked.get(
        STANDALONELIST_URL,
        status=200,
        body=load_fixture("standalonelist.json"),
    )


@pytest.mark.asyncio
async def test_meterhistory_summary_no_sessions_message() -> None:
    """NoSessions response shows the warning and no CSV."""
    with aioresponses() as mocked:
        _add_meterhistory_responses(
            mocked,
            meterhistory_fixture="meterhistory-nosessions.json",
        )

        capture = io.StringIO()
        with redirect_stdout(capture):
            await meterhistory(
                host="example.com",
                password="secret",
                export=False,
                quiet=False,
            )

    out = capture.getvalue()
    assert "No sessions found" in out


@pytest.mark.asyncio
async def test_meterhistory_summary_shows_totals_and_table() -> None:
    """With sessions, summary shows total kWh, session count, and token table."""
    with aioresponses() as mocked:
        _add_meterhistory_responses(mocked, meterhistory_fixture="meterhistory.json")

        capture = io.StringIO()
        with redirect_stdout(capture):
            await meterhistory(
                host="example.com",
                password="secret",
                export=False,
                quiet=False,
            )

    out = capture.getvalue()
    # Total span: max(end) - min(start) = 1998041111 - 1956857265 = 41183846 mWh
    assert re.search(r"41[.,]184", out), out
    assert "kWh" in out
    assert re.search(r"Sessions:\s*2\b", out), out
    assert "Energy by authorisation token" in out
    assert "123456789A1234" in out
    assert "12345E01234567" in out


@pytest.mark.asyncio
async def test_meterhistory_export_writes_csv(
    tmp_path: Path,
) -> None:
    """With --export, meter history is written to the given CSV path."""
    with aioresponses() as mocked:
        _add_meterhistory_responses(mocked, meterhistory_fixture="meterhistory.json")

        out_file = tmp_path / "meter.csv"
        await meterhistory(
            host="example.com",
            password="secret",
            export=True,
            filename=str(out_file),
            quiet=True,
        )

    assert out_file.is_file()
    text = out_file.read_text(encoding="utf-8")
    assert "12-34-Z56-P4R" in text
    assert "123456789A1234" in text


def test_a_bare_date_covers_the_whole_day() -> None:
    """Test a stop bound given as a date runs to the end of it.

    Stopping at midnight would drop the day someone just asked for.
    """
    start = normalize_meterhistory_bound("2026-08-30")
    stop = normalize_meterhistory_bound("2026-08-30", is_stop=True)

    assert start is not None
    assert stop is not None
    assert start.isoformat() == "2026-08-30T00:00:00+00:00"
    assert stop.isoformat() == "2026-08-30T23:59:59+00:00"


@pytest.mark.parametrize(
    "value",
    [
        "1756555555",
        "yesterday",
        "30/08/2026",
    ],
)
def test_a_bound_the_charger_would_ignore_is_refused(value: str) -> None:
    """Test a bound that is not a time is turned away here.

    The charger reads these as ISO 8601 and quietly hands back its entire
    history for anything else, a Unix timestamp included, so passing one
    on would answer a question nobody asked.
    """
    with pytest.raises(typer.BadParameter):
        normalize_meterhistory_bound(value)


@pytest.mark.asyncio
async def test_the_time_range_reaches_the_charger_as_iso() -> None:
    """Test the bounds are handed over in the one format the charger reads.

    The mock is registered on the exact URL, so it only answers if the
    query was built that way: anything else fails to match.
    """
    with aioresponses() as mocked:
        mocked.post(LOGIN_URL, status=200, body="", content_type="text/plain")
        mocked.get(
            f"{METERHISTORY_URL}?StartTime=2026-08-29T06:00:00%2B00:00"
            "&StopTime=2026-08-30T18:30:00%2B00:00",
            status=200,
            body=load_fixture("meterhistory.json"),
        )

        async with Peblar(host=HOST) as peblar:
            await peblar.login(password="secret")
            history = await peblar.meter_history(
                start=datetime(2026, 8, 29, 6, 0, tzinfo=UTC),
                stop=datetime(2026, 8, 30, 18, 30, tzinfo=UTC),
            )

    assert history.session
