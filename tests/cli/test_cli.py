"""Tests for the Peblar CLI."""

# pylint: disable=redefined-outer-name
from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import click
import orjson
import pytest
from typer.main import get_command
from typer.testing import CliRunner

from peblar.cli import cli, convert_to_string
from peblar.exceptions import (
    PeblarAuthenticationError,
    PeblarBadRequestError,
    PeblarRateLimitError,
    PeblarUnsupportedFirmwareVersionError,
)
from peblar.models import (
    PeblarHealth,
    PeblarMeter,
    PeblarSystem,
    PeblarSystemInformation,
    PeblarUserConfiguration,
    PeblarVersions,
)
from tests import load_fixture

if TYPE_CHECKING:
    from syrupy.assertion import SnapshotAssertion


@pytest.fixture(autouse=True)
def stable_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force deterministic Rich rendering for stable snapshots."""
    monkeypatch.setenv("COLUMNS", "100")
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("TERM", "dumb")


@pytest.fixture
def runner() -> CliRunner:
    """Return a CLI runner for invoking the Typer app."""
    return CliRunner()


def _mock_peblar(**method_returns: object) -> MagicMock:
    """Return a MagicMock that stands in for the Peblar class.

    Keyword arguments map method names to their return values, e.g.
    ``_mock_peblar(system_information=info_obj, login=None)``.
    """
    client = AsyncMock()
    for method_name, return_value in method_returns.items():
        getattr(client, method_name).return_value = return_value

    instance = AsyncMock()
    instance.__aenter__.return_value = client
    instance.__aexit__.return_value = None

    return MagicMock(return_value=instance)


def _mock_peblar_with_api(
    api_methods: dict[str, object],
    **peblar_methods: object,
) -> MagicMock:
    """Mock Peblar with a rest_api() that yields a mock PeblarApi.

    ``api_methods`` maps PeblarApi method names to return values.
    ``peblar_methods`` maps Peblar method names to return values.
    """
    api = AsyncMock()
    for method_name, return_value in api_methods.items():
        getattr(api, method_name).return_value = return_value
    api.__aenter__ = AsyncMock(return_value=api)
    api.__aexit__ = AsyncMock(return_value=None)

    peblar_methods["rest_api"] = api
    return _mock_peblar(**peblar_methods)


def _invoke(
    runner: CliRunner,
    args: list[str],
    mock_cls: MagicMock,
) -> tuple[int, str]:
    """Invoke the CLI with a mocked Peblar class."""
    with patch("peblar.cli.Peblar", mock_cls):
        result = runner.invoke(cli, args)
    return result.exit_code, result.output


# Host and password flags reused across all command invocations.
_AUTH = ["--host", "192.168.1.1", "--password", "secret"]


# ---------------------------------------------------------------------------
# CLI structure
# ---------------------------------------------------------------------------


def test_cli_structure(snapshot: SnapshotAssertion) -> None:
    """The CLI exposes the expected commands and options."""
    group = get_command(cli)
    assert isinstance(group, click.Group)
    structure = {
        name: sorted(param.name for param in subcommand.params)
        for name, subcommand in sorted(group.commands.items())
    }
    assert structure == snapshot


# ---------------------------------------------------------------------------
# Command tests (main API)
# ---------------------------------------------------------------------------


def test_versions(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """Versions command renders a table of current and available versions."""
    versions = PeblarVersions.from_json(load_fixture("versions_current.json"))
    available = PeblarVersions.from_json(load_fixture("versions_available.json"))
    mock_cls = _mock_peblar(
        login=None,
        current_versions=versions,
        available_versions=available,
    )
    exit_code, output = _invoke(runner, ["versions", *_AUTH], mock_cls)
    assert exit_code == 0
    assert output == snapshot


def test_info(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """Info command renders a table of system information."""
    info = PeblarSystemInformation.from_json(
        load_fixture("system_information.json"),
    )
    mock_cls = _mock_peblar(login=None, system_information=info)
    exit_code, output = _invoke(runner, ["info", *_AUTH], mock_cls)
    assert exit_code == 0
    assert output == snapshot


def test_config(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """Config command renders a table of user configuration."""
    config = PeblarUserConfiguration.from_json(
        load_fixture("user_configuration.json"),
    )
    mock_cls = _mock_peblar(login=None, user_configuration=config)
    exit_code, output = _invoke(runner, ["config", *_AUTH], mock_cls)
    assert exit_code == 0
    assert output == snapshot


def test_config_set_charge_limit(runner: CliRunner) -> None:
    """Config command with --charge-current-limit PATCHes the charger."""
    mock_cls = _mock_peblar(login=None, update_user_configuration=None)
    exit_code, output = _invoke(
        runner, ["config", *_AUTH, "--charge-current-limit", "10"], mock_cls
    )
    assert exit_code == 0
    assert "Success!" in output


def test_config_charge_limit_too_low(runner: CliRunner) -> None:
    """Config command rejects a charge limit below 6A."""
    mock_cls = _mock_peblar(login=None)
    exit_code, _ = _invoke(
        runner, ["config", *_AUTH, "--charge-current-limit", "3"], mock_cls
    )
    assert exit_code != 0


def test_household_limit_set(runner: CliRunner) -> None:
    """Household-limit command with --limit PATCHes the charger."""
    mock_cls = _mock_peblar(login=None, update_user_configuration=None)
    exit_code, output = _invoke(
        runner,
        ["household-limit", *_AUTH, "--limit", "7500", "--enable"],
        mock_cls,
    )
    assert exit_code == 0
    assert "Success!" in output


def test_household_limit_show(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """Household-limit command without flags shows the current setting."""
    config = PeblarUserConfiguration.from_json(
        load_fixture("user_configuration.json"),
    )
    mock_cls = _mock_peblar(login=None, user_configuration=config)
    exit_code, output = _invoke(runner, ["household-limit", *_AUTH], mock_cls)
    assert exit_code == 0
    assert output == snapshot


def test_household_limit_enable_disable_conflict(runner: CliRunner) -> None:
    """Household-limit command rejects --enable and --disable together."""
    mock_cls = _mock_peblar(login=None)
    exit_code, _ = _invoke(
        runner,
        ["household-limit", *_AUTH, "--enable", "--disable"],
        mock_cls,
    )
    assert exit_code != 0


def test_identify(runner: CliRunner) -> None:
    """Identify command invokes peblar.identify()."""
    mock_cls = _mock_peblar(login=None, identify=None)
    exit_code, _ = _invoke(runner, ["identify", *_AUTH], mock_cls)
    assert exit_code == 0


def test_unlock(runner: CliRunner) -> None:
    """Unlock command invokes peblar.socket_unlock()."""
    mock_cls = _mock_peblar(login=None, socket_unlock=None)
    exit_code, _ = _invoke(runner, ["unlock", *_AUTH], mock_cls)
    assert exit_code == 0


def test_reboot(runner: CliRunner) -> None:
    """Reboot command invokes peblar.reboot()."""
    mock_cls = _mock_peblar(login=None, reboot=None)
    exit_code, _ = _invoke(runner, ["reboot", *_AUTH], mock_cls)
    assert exit_code == 0


# ---------------------------------------------------------------------------
# Command tests (Local REST API)
# ---------------------------------------------------------------------------


def test_health(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """Health command renders a health table via the Local REST API."""
    health = PeblarHealth.from_json(load_fixture("health.json"))
    mock_cls = _mock_peblar_with_api({"health": health}, login=None)
    exit_code, output = _invoke(runner, ["health", *_AUTH], mock_cls)
    assert exit_code == 0
    assert output == snapshot


def test_meter(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """Meter command renders a meter table via the Local REST API."""
    meter = PeblarMeter.from_json(load_fixture("meter.json"))
    mock_cls = _mock_peblar_with_api({"meter": meter}, login=None)
    exit_code, output = _invoke(runner, ["meter", *_AUTH], mock_cls)
    assert exit_code == 0
    assert output == snapshot


def test_system(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """System command renders a system status table via the Local REST API."""
    system = PeblarSystem.from_json(load_fixture("system.json"))
    mock_cls = _mock_peblar_with_api({"system": system}, login=None)
    exit_code, output = _invoke(runner, ["system", *_AUTH], mock_cls)
    assert exit_code == 0
    assert output == snapshot


# ---------------------------------------------------------------------------
# --quiet / -q flag
# ---------------------------------------------------------------------------


def test_identify_quiet_suppresses_success(runner: CliRunner) -> None:
    """Identify with --quiet suppresses the success message."""
    mock_cls = _mock_peblar(login=None, identify=None)
    exit_code, output = _invoke(runner, ["identify", *_AUTH, "--quiet"], mock_cls)
    assert exit_code == 0
    assert "Success" not in output


def test_identify_quiet_short_flag(runner: CliRunner) -> None:
    """Identify with -q suppresses the success message."""
    mock_cls = _mock_peblar(login=None, identify=None)
    exit_code, output = _invoke(runner, ["identify", *_AUTH, "-q"], mock_cls)
    assert exit_code == 0
    assert "Success" not in output


def test_versions_quiet_still_prints_table(
    runner: CliRunner,
    snapshot: SnapshotAssertion,
) -> None:
    """Versions with --quiet still prints the table (read-only command)."""
    versions = PeblarVersions.from_json(load_fixture("versions_current.json"))
    available = PeblarVersions.from_json(load_fixture("versions_available.json"))
    mock_cls = _mock_peblar(
        login=None,
        current_versions=versions,
        available_versions=available,
    )
    exit_code, output = _invoke(runner, ["versions", *_AUTH, "--quiet"], mock_cls)
    assert exit_code == 0
    assert output == snapshot


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------


def test_authentication_error_handler(
    capsys: pytest.CaptureFixture[str],
    snapshot: SnapshotAssertion,
) -> None:
    """Authentication error handler prints a panel and exits with 1."""
    handler = cli.error_handlers[PeblarAuthenticationError]
    with pytest.raises(SystemExit) as exc_info:
        handler(PeblarAuthenticationError("bad password"))
    assert exc_info.value.code == 1
    assert capsys.readouterr().out == snapshot


def test_unsupported_firmware_error_handler(
    capsys: pytest.CaptureFixture[str],
    snapshot: SnapshotAssertion,
) -> None:
    """Unsupported firmware error handler prints a panel and exits with 1."""
    handler = cli.error_handlers[PeblarUnsupportedFirmwareVersionError]
    with pytest.raises(SystemExit) as exc_info:
        handler(PeblarUnsupportedFirmwareVersionError("too old"))
    assert exc_info.value.code == 1
    assert capsys.readouterr().out == snapshot


def test_rate_limit_error_handler(
    capsys: pytest.CaptureFixture[str],
    snapshot: SnapshotAssertion,
) -> None:
    """Rate limit error handler prints a panel and exits with 1."""
    handler = cli.error_handlers[PeblarRateLimitError]
    with pytest.raises(SystemExit) as exc_info:
        handler(PeblarRateLimitError("slow down"))
    assert exc_info.value.code == 1
    assert capsys.readouterr().out == snapshot


def test_bad_request_message_survives_rich_markup(
    runner: CliRunner,
) -> None:
    """Charger error text is printed verbatim, tags and all.

    The message carries the charger's own `statusmsg`, so anything in it
    that looks like Rich markup must not be swallowed on the way out.
    """
    reason = "limit [/] rejected [bold] see [link=http://x]docs[/link]"
    mock_cls = _mock_peblar(login=None)
    mock_cls.return_value.__aenter__.return_value.meter_history.side_effect = (
        PeblarBadRequestError(f"Bad request sent to the Peblar charger: {reason}")
    )
    exit_code, output = _invoke(runner, ["meterhistory", *_AUTH], mock_cls)
    assert exit_code == 1
    assert reason in output


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "N/A"),
        (True, "✅"),
        (False, "❌"),
        ({}, ""),
        ({"address": "meter-1"}, "address: meter-1"),
        ({"address": "meter-1", "port": 8080}, "address: meter-1, port: 8080"),
        ("plain", "plain"),
        (16, "16"),
    ],
)
def test_convert_to_string(value: object, expected: str) -> None:
    """Values render readably, including absent ones and multi-key blobs."""
    assert convert_to_string(value) == expected


# Every field newer firmware added, so the older firmware tests below drop
# all of them rather than a sample.
NEWER_SYSTEM_INFORMATION_KEYS = (
    "HwHas4pRelay",
    "HwHasDualSocket",
    "HwHasShutter",
    "HwUKCompliant",
    "NorFlash",
)
NEWER_USER_CONFIGURATION_KEYS = (
    "ConnectHubVisibility",
    "CustomCustomerId",
    "Iso15118CommunicationEnable",
    "SboAllowed",
    "SboEnabled",
    "SessionDownloadAllowed",
    "UserDefinedHouseholdPowerLimitSourceParameters",
)


def test_info_on_older_firmware_shows_no_literal_none(
    runner: CliRunner,
) -> None:
    """Older firmware omits fields, and the table must not print "None"."""
    data = orjson.loads(load_fixture("system_information.json"))
    for key in NEWER_SYSTEM_INFORMATION_KEYS:
        del data[key]

    info = PeblarSystemInformation.from_dict(data)
    mock_cls = _mock_peblar(login=None, system_information=info)
    exit_code, output = _invoke(runner, ["info", *_AUTH], mock_cls)
    assert exit_code == 0
    assert "None" not in output
    # One "N/A" for every field the charger did not report.
    assert output.count("N/A") == len(NEWER_SYSTEM_INFORMATION_KEYS)


def test_config_on_older_firmware_shows_no_literal_none(
    runner: CliRunner,
) -> None:
    """Older firmware omits settings, and the table must not print "None"."""
    data = orjson.loads(load_fixture("user_configuration.json"))
    for key in NEWER_USER_CONFIGURATION_KEYS:
        del data[key]

    config = PeblarUserConfiguration.from_dict(data)
    mock_cls = _mock_peblar(login=None, user_configuration=config)
    exit_code, output = _invoke(runner, ["config", *_AUTH], mock_cls)
    assert exit_code == 0
    assert "None" not in output
    # The parameter blob defaults to an empty dict, not None, so it renders
    # blank instead of "N/A"; every other absent setting shows "N/A".
    assert output.count("N/A") == len(NEWER_USER_CONFIGURATION_KEYS) - 1


def test_authorize_by_uid(runner: CliRunner) -> None:
    """Authorize command presents a token by its UID."""
    mock_cls = _mock_peblar_with_api({"authorize_charge_session": None}, login=None)
    exit_code, output = _invoke(
        runner, ["authorize", *_AUTH, "--uid", "0123456789ABCD"], mock_cls
    )
    assert exit_code == 0
    assert "Success" in output


def test_authorize_by_name(runner: CliRunner) -> None:
    """Authorize command presents a token by its description."""
    mock_cls = _mock_peblar_with_api({"authorize_charge_session": None}, login=None)
    exit_code, output = _invoke(
        runner, ["authorize", *_AUTH, "--name", "My RFID Card"], mock_cls
    )
    assert exit_code == 0
    assert "Success" in output


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--uid", "0123456789ABCD", "--name", "My RFID Card"],
    ],
    ids=["neither", "both"],
)
def test_authorize_requires_exactly_one_identifier(
    runner: CliRunner,
    args: list[str],
) -> None:
    """Authorize command rejects zero or two token identifiers."""
    mock_cls = _mock_peblar_with_api({"authorize_charge_session": None}, login=None)
    exit_code, output = _invoke(runner, ["authorize", *_AUTH, *args], mock_cls)
    assert exit_code != 0
    assert "exactly one" in output


def test_unsupported_firmware_handler_shows_the_versions(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The firmware panel shows what the charger runs, not a placeholder."""
    handler = cli.error_handlers[PeblarUnsupportedFirmwareVersionError]
    with pytest.raises(SystemExit):
        handler(
            PeblarUnsupportedFirmwareVersionError(
                "The local REST API requires firmware 1.6 or later, "
                "this charger runs 1.5.0."
            )
        )
    output = capsys.readouterr().out
    assert "1.6" in output
    assert "1.5.0" in output
    assert "XXX" not in output
