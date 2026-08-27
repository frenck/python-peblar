"""Asynchronous Python client for Peblar EV chargers."""

import asyncio
import contextlib
import csv
import functools
import json
import locale
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

import typer
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from yarl import URL
from zeroconf import ServiceStateChange, Zeroconf
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

from peblar.const import (
    AccessMode,
    CPState,
    LedBrightness,
    PackageType,
    SmartChargingMode,
    SoundVolume,
)
from peblar.exceptions import (
    PeblarAuthenticationError,
    PeblarBadRequestError,
    PeblarConnectionError,
    PeblarError,
    PeblarUnsupportedFirmwareVersionError,
)
from peblar.models import (
    PeblarMeterHistory,
    PeblarMeterHistorySession,
    PeblarRfidToken,
    PeblarSetUserConfiguration,
)
from peblar.peblar import Peblar

from .async_typer import AsyncTyper

cli = AsyncTyper(help="Peblar CLI", no_args_is_help=True, add_completion=False)
console = Console()

QUIET_OPTION = typer.Option(
    ...,
    "--quiet",
    "-q",
    help="Be quiet on success; read-only commands still print tables and results",
    envvar="PEBLAR_QUIET",
)


def print_cli_success(*, quiet: bool, message: str) -> None:
    """Print a success confirmation unless --quiet (data and tables still print)."""
    if quiet:
        return
    console.print(message)


def convert_to_string(value: object) -> str:
    """Convert a value to a string."""
    if isinstance(value, bool):
        return "✅" if value else "❌"
    if isinstance(value, dict):
        return "".join(f"{key}: {value}" for key, value in value.items())
    return str(value)


def format_meterhistory_time(timestamp: int | None, timezone: ZoneInfo) -> str:
    """Format a unix timestamp for meter history CSV output."""
    if timestamp is None:
        return "Unknown"
    return (
        datetime.fromtimestamp(timestamp, UTC)
        .astimezone(timezone)
        .strftime("%d/%m/%Y %H:%M:%S")
    )


def format_meterhistory_energy(energy_mwh: int | None) -> str:
    """Format mWh to kWh with three decimals."""
    if energy_mwh is None:
        return "Unknown"
    return f"{energy_mwh / 1_000_000:,.3f}"


def normalize_meterhistory_bound(
    value: str | None,
    *,
    is_stop: bool = False,
) -> str | None:
    """Convert a date-only meter history bound to UTC ISO format."""
    if value is None or "T" in value:
        return value

    for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            bound = datetime.strptime(value, fmt)  # noqa: DTZ007
            break
        except ValueError:
            continue
    else:
        return value

    if is_stop:
        bound = bound.replace(hour=23, minute=59, second=59)

    return bound.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


def meterhistory_filename_part(value: str | None) -> str:
    """Format a meter history bound value for use in filenames."""
    if value is None:
        return "all"

    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return value.replace(":", "-").replace("T", "_")

    return dt.strftime("%d-%m-%Y_%H-%M-%S")


def meterhistory_total_energy_mwh(history: PeblarMeterHistory) -> int:
    """Return total energy in mWh: max end reading minus min start across sessions."""
    if not history.session:
        return 0
    ends = [
        s.session_end_energy_mwh
        for s in history.session
        if s.session_end_energy_mwh is not None
    ]
    if not ends:
        return 0
    max_end = max(ends)
    min_start = min(s.session_start_energy_mwh for s in history.session)
    return max(0, max_end - min_start)


async def meterhistory_fetch_data(
    peblar: Peblar,
    *,
    start: str | None,
    stop: str | None,
) -> tuple[str | None, str | None, PeblarMeterHistory, list[PeblarRfidToken]]:
    """Fetch and normalize data needed for meter history export."""
    normalized_start = normalize_meterhistory_bound(start)
    normalized_stop = normalize_meterhistory_bound(stop, is_stop=True)
    try:
        history = await peblar.meter_history(
            start=normalized_start,
            stop=normalized_stop,
        )
    except PeblarBadRequestError as exc:
        console.print(f"❌[red]Bad request: {exc}")
        raise typer.Exit(code=1) from exc
    tokens = await peblar.rfid_tokens()
    return normalized_start, normalized_stop, history, tokens


async def meterhistory_export_csv(
    peblar: Peblar,
    *,
    start: str | None,
    stop: str | None,
    filename: str | None,
) -> str | None:
    """Fetch meter history and export it to CSV, or None when no sessions exist."""
    normalized_start, normalized_stop, history, tokens = await meterhistory_fetch_data(
        peblar,
        start=start,
        stop=stop,
    )

    if not history.session or not history.meta_data:
        return None

    time_range = ""
    if normalized_start is not None or normalized_stop is not None:
        time_range = (
            f"{meterhistory_filename_part(normalized_start)}_"
            f"{meterhistory_filename_part(normalized_stop)}_"
        )
    output_filename = (
        filename or f"meter-data_{time_range}sn-{history.meta_data.product_sn}.csv"
    )
    token_descriptions = {
        token.rfid_token_uid: token.rfid_token_description for token in tokens
    }

    await asyncio.to_thread(
        write_meterhistory_csv,
        output_filename,
        history,
        token_descriptions,
        ZoneInfo(history.meta_data.time_zone),
        meterhistory_total_energy_mwh(history),
    )
    return output_filename


def meterhistory_summary_rfid_tag(
    auth_token: str | None,
    token_descriptions: dict[str, str],
) -> str:
    """RFID name from charger config; empty if unknown or no token."""
    if auth_token is None:
        return ""
    return token_descriptions.get(auth_token, "")


def meterhistory_summary_auth_token_cell(auth_token: str | None) -> str:
    """Authorisation token UID; empty when the session has no token."""
    return auth_token or ""


@functools.lru_cache(maxsize=1)
def _locale_numeric_usable() -> bool:
    """Whether LC_NUMERIC was taken from the environment (cached)."""
    try:
        locale.setlocale(locale.LC_NUMERIC, "")
    except locale.Error:
        return False
    return True


def format_locale_decimal(value: float, *, digits: int = 3) -> str:
    """Format a float using locale thousands and decimal separators."""
    if _locale_numeric_usable():
        return locale.format_string(f"%.{digits}f", value, grouping=True)
    return f"{value:,.{digits}f}"


def format_locale_int(value: int) -> str:
    """Format an int using locale thousands grouping."""
    if _locale_numeric_usable():
        return locale.format_string("%d", value, grouping=True)
    return f"{value:,}"


def meterhistory_aggregate_by_auth_token(
    history: PeblarMeterHistory,
) -> dict[str | None, tuple[int, int]]:
    """Map auth_token -> (session_count, total_session_energy_mwh).

    Session energy is end minus start when end is known; otherwise the session
    contributes to the count only (0 mWh to the sum).
    """
    counts: dict[str | None, int] = defaultdict(int)
    energies: dict[str | None, int] = defaultdict(int)
    for session in history.session:
        key = session.auth_token
        counts[key] += 1
        if session.session_end_energy_mwh is not None:
            energies[key] += (
                session.session_end_energy_mwh - session.session_start_energy_mwh
            )
    keys = set(counts) | set(energies)
    return {k: (counts[k], energies[k]) for k in keys}


def meterhistory_print_summary(
    history: PeblarMeterHistory,
    tokens: list[PeblarRfidToken],
) -> None:
    """Print total span energy, session count, and per-auth-token table."""
    token_descriptions = {
        token.rfid_token_uid: token.rfid_token_description for token in tokens
    }
    total_mwh = meterhistory_total_energy_mwh(history)
    total_kwh = total_mwh / 1_000_000
    n_sessions = len(history.session)
    console.print(f"Total energy (meter span): {format_locale_decimal(total_kwh)} kWh")
    console.print(f"Sessions: {format_locale_int(n_sessions)}")

    table = Table(title="Energy by authorisation token")
    table.add_column("Authorisation token", style="cyan")
    table.add_column("RFID tag", style="cyan")
    table.add_column("Sessions", justify="right", style="bold")
    table.add_column("Total energy (kWh)", justify="right", style="bold")

    agg = meterhistory_aggregate_by_auth_token(history)

    def sort_key(item: tuple[str | None, tuple[int, int]]) -> tuple[float, str]:
        token, (_cnt, mwh_sum) = item
        kwh = mwh_sum / 1_000_000
        return (-kwh, token or "")

    for auth_token, (cnt, mwh_sum) in sorted(agg.items(), key=sort_key):
        kwh = mwh_sum / 1_000_000
        table.add_row(
            meterhistory_summary_auth_token_cell(auth_token),
            meterhistory_summary_rfid_tag(auth_token, token_descriptions),
            format_locale_int(cnt),
            format_locale_decimal(kwh),
        )
    console.print(table)


@dataclass(frozen=True, slots=True)
class MeterHistoryCliOptions:
    """CLI options for meter history fetch / export."""

    start: str | None
    stop: str | None
    filename: str | None
    export: bool
    quiet: bool


async def meterhistory_run_with_client(
    peblar: Peblar,
    *,
    options: MeterHistoryCliOptions,
) -> None:
    """Fetch meter history and either export CSV or print summary."""
    if options.export:
        output_filename = await meterhistory_export_csv(
            peblar,
            start=options.start,
            stop=options.stop,
            filename=options.filename,
        )
        if not options.quiet:
            if output_filename is None:
                console.print(
                    "⚠️  [yellow]No sessions found for the requested time range."
                )
            else:
                console.print(f"✅[green]Created CSV file: {output_filename}")
        return
    _ns, _ne, history, tokens = await meterhistory_fetch_data(
        peblar,
        start=options.start,
        stop=options.stop,
    )
    if history.session:
        meterhistory_print_summary(history, tokens)
    else:
        console.print("⚠️  [yellow]No sessions found for the requested time range.")


def meterhistory_auth_token_display(
    auth_token: str | None,
    token_descriptions: dict[str, str],
) -> str:
    """Resolve auth token to user-friendly display value."""
    if auth_token is None:
        return ""
    if description := token_descriptions.get(auth_token):
        return f"{description} ({auth_token})"
    return auth_token


def meterhistory_session_row(
    index: int,
    session: PeblarMeterHistorySession,
    timezone: ZoneInfo,
    token_descriptions: dict[str, str],
    corrupted_session: list[bool],
) -> list[str | int]:
    """Build one CSV row for a single meter history session."""
    session_end_energy_mwh = session.session_end_energy_mwh
    session_energy = "Unknown"
    cost = "Unknown"
    if session_end_energy_mwh is not None:
        energy_mwh = session_end_energy_mwh - session.session_start_energy_mwh
        session_energy = format_meterhistory_energy(energy_mwh)
        cost = "0.00"

    is_corrupted = index - 1 < len(corrupted_session) and corrupted_session[index - 1]
    return [
        index,
        format_meterhistory_time(session.session_start_time, timezone),
        format_meterhistory_time(session.session_end_time, timezone),
        format_meterhistory_energy(session.session_start_energy_mwh),
        format_meterhistory_energy(session_end_energy_mwh),
        session_energy,
        cost,
        meterhistory_auth_token_display(session.auth_token, token_descriptions),
        "Fail" if is_corrupted else "Pass",
    ]


def write_meterhistory_csv(
    filename: str,
    history: PeblarMeterHistory,
    token_descriptions: dict[str, str],
    timezone: ZoneInfo,
    total_energy_mwh: int,
) -> None:
    """Write meter history rows to CSV."""
    with Path(filename).open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.writer(csv_file, delimiter=";", lineterminator="\n")
        writer.writerow(["# Charger information"])
        writer.writerow(
            [
                "# Serial number",
                history.meta_data.product_sn if history.meta_data else "unknown",
            ]
        )
        writer.writerow(
            [
                "# Meter Type",
                "MID certified"
                if history.meta_data and history.meta_data.mid_certified
                else "Not MID certified",
            ]
        )
        writer.writerow(
            [
                "# Timezone",
                history.meta_data.time_zone if history.meta_data else "unknown",
            ]
        )
        writer.writerow(["# Report details"])
        writer.writerow(["# Currency", "EUR"])
        writer.writerow(["# Price per kWh", "0.00", "(User defined)"])
        writer.writerow(["# Totals"])
        writer.writerow(
            [
                "# Total energy used (kWh)",
                format_meterhistory_energy(total_energy_mwh),
            ]
        )
        writer.writerow(["# Total cost", "0.00"])
        writer.writerow([])
        writer.writerow(
            [
                "Session number",
                "Start time",
                "Stop time",
                "Start energy (kWh)",
                "Stop energy (kWh)",
                "Total session energy (kWh)",
                "Cost",
                "Authorisation token",
                "Session validation",
            ]
        )

        for index, session in enumerate(history.session, start=1):
            writer.writerow(
                meterhistory_session_row(
                    index,
                    session,
                    timezone,
                    token_descriptions,
                    history.corrupted_session,
                )
            )


@cli.error_handler(PeblarAuthenticationError)
def authentication_error_handler(_: PeblarAuthenticationError) -> None:
    """Handle authentication errors."""
    message = """
    The provided Peblar charger password is invalid.
    """
    panel = Panel(
        message,
        expand=False,
        title="Authentication error",
        border_style="red bold",
    )
    console.print(panel)
    sys.exit(1)


# @cli.error_handler(PeblarConnectionError)
def connection_error_handler(_: PeblarConnectionError) -> None:
    """Handle connection errors."""
    message = """
    Could not connect to the specified Peblar charger. Please make sure that
    the charger is powered on, connected to the network and that you have
    specified the correct IP address or hostname.

    If you are not sure what the IP address or hostname of your Peblar charger
    is, you can use the scan command to find it:

    peblar scan
    """
    panel = Panel(
        message,
        expand=False,
        title="Connection error",
        border_style="red bold",
    )
    console.print(panel)
    sys.exit(1)


@cli.error_handler(PeblarUnsupportedFirmwareVersionError)
def unsupported_firmware_version_error_handler(
    _: PeblarUnsupportedFirmwareVersionError,
) -> None:
    """Handle unsupported version errors."""
    message = """
    The specified Peblar charger is running an unsupported firmware version.

    The tooling currently only supports firmware versions XXX and higher.
    """
    panel = Panel(
        message,
        expand=False,
        title="Unsupported firmware version",
        border_style="red bold",
    )
    console.print(panel)
    sys.exit(1)


@cli.command("versions")
async def versions(
    host: Annotated[
        str,
        typer.Option(
            help="Peblar charger IP address or hostname",
            prompt="Host address",
            show_default=False,
            envvar="PEBLAR_HOST",
        ),
    ],
    password: Annotated[
        str,
        typer.Option(
            help="Peblar charger login password",
            prompt="Password",
            show_default=False,
            hide_input=True,
            envvar="PEBLAR_PASSWORD",
        ),
    ],
    quiet: Annotated[bool, QUIET_OPTION] = False,  # noqa: ARG001  # pylint: disable=unused-argument
) -> None:
    """Get the software version information of the Peblar charger."""
    async with Peblar(host=host) as peblar:
        await peblar.login(password=password)
        current = await peblar.current_versions()
        available = await peblar.available_versions()

    table = Table(title="Peblar charger versions")
    table.add_column("Type", style="cyan bold")
    table.add_column("Installed version", style="cyan bold")
    table.add_column("Available version", style="cyan bold")

    firmware = "✅" if current.firmware == available.firmware else "⬆️"
    customization = "✅" if current.customization == available.customization else "⬆️"

    table.add_row(
        "Firmware",
        current.firmware,
        f"{firmware} {available.firmware}",
    )
    table.add_row(
        "Customization",
        current.customization,
        f"{customization} {available.customization}",
    )

    console.print(table)


@cli.command("identify")
async def identify(
    host: Annotated[
        str,
        typer.Option(
            help="Peblar charger IP address or hostname",
            prompt="Host address",
            show_default=False,
            envvar="PEBLAR_HOST",
        ),
    ],
    password: Annotated[
        str,
        typer.Option(
            help="Peblar charger login password",
            prompt="Password",
            show_default=False,
            hide_input=True,
            envvar="PEBLAR_PASSWORD",
        ),
    ],
    quiet: Annotated[bool, QUIET_OPTION] = False,
) -> None:
    """Flash the LEDs on the Peblar charger to identify it."""
    status_ctx = (
        contextlib.nullcontext()
        if quiet
        else console.status("[cyan]Identifying...", spinner="toggle12")
    )
    with status_ctx:
        async with Peblar(host=host) as peblar:
            await peblar.login(password=password)
            await peblar.identify()
    print_cli_success(quiet=quiet, message="✅[green]Success!")


@cli.command("lock")
async def lock_cmd(
    host: Annotated[
        str,
        typer.Option(
            help="Peblar charger IP address or hostname",
            prompt="Host address",
            show_default=False,
            envvar="PEBLAR_HOST",
        ),
    ],
    password: Annotated[
        str,
        typer.Option(
            help="Peblar charger login password",
            prompt="Password",
            show_default=False,
            hide_input=True,
            envvar="PEBLAR_PASSWORD",
        ),
    ],
    quiet: Annotated[bool, QUIET_OPTION] = False,
) -> None:
    """Lock the socket of the Peblar charger.

    Sets the persistent lock so the socket stays locked between sessions.
    There is no immediate lock action; the charger only supports immediate
    unlock (see the unlock command).
    """
    status_ctx = (
        contextlib.nullcontext()
        if quiet
        else console.status("[cyan]Locking...", spinner="toggle12")
    )
    with status_ctx:
        async with Peblar(host=host) as peblar:
            await peblar.login(password=password)
            await peblar.socket_lock(locked=True)
    print_cli_success(quiet=quiet, message="✅[green]Success!")


@cli.command("unlock")
async def unlock_cmd(
    host: Annotated[
        str,
        typer.Option(
            help="Peblar charger IP address or hostname",
            prompt="Host address",
            show_default=False,
            envvar="PEBLAR_HOST",
        ),
    ],
    password: Annotated[
        str,
        typer.Option(
            help="Peblar charger login password",
            prompt="Password",
            show_default=False,
            hide_input=True,
            envvar="PEBLAR_PASSWORD",
        ),
    ],
    persist: Annotated[
        bool,
        typer.Option(
            help="Also clear the persistent lock setting",
        ),
    ] = False,
    quiet: Annotated[bool, QUIET_OPTION] = False,
) -> None:
    """Unlock the socket of the Peblar charger.

    Triggers an immediate unlock. Pass --persist to also clear the persistent
    lock setting so the socket does not re-lock between sessions.
    """
    status_ctx = (
        contextlib.nullcontext()
        if quiet
        else console.status("[cyan]Unlocking...", spinner="toggle12")
    )
    with status_ctx:
        async with Peblar(host=host) as peblar:
            await peblar.login(password=password)
            await peblar.socket_unlock()
            if persist:
                await peblar.socket_lock(locked=False)
    print_cli_success(quiet=quiet, message="✅[green]Success!")


@cli.command("household-limit")
# pylint: disable=too-many-arguments,too-many-positional-arguments
async def household_limit_cmd(
    host: Annotated[
        str,
        typer.Option(
            help="Peblar charger IP address or hostname",
            prompt="Host address",
            show_default=False,
            envvar="PEBLAR_HOST",
        ),
    ],
    password: Annotated[
        str,
        typer.Option(
            help="Peblar charger login password",
            prompt="Password",
            show_default=False,
            hide_input=True,
            envvar="PEBLAR_PASSWORD",
        ),
    ],
    limit: Annotated[
        int | None,
        typer.Option(
            help="Household power limit in watts",
            show_default=False,
        ),
    ] = None,
    enable: Annotated[
        bool,
        typer.Option(
            help="Enable the household power limit",
        ),
    ] = False,
    disable: Annotated[
        bool,
        typer.Option(
            help="Disable the household power limit",
        ),
    ] = False,
    quiet: Annotated[bool, QUIET_OPTION] = False,
) -> None:
    """Show or change the household power limit.

    Without flags, shows the current setting. Pass --limit to set the
    power limit (in watts), --enable / --disable to toggle it.
    """
    if enable and disable:
        msg = "--enable cannot be used with --disable."
        raise typer.BadParameter(msg)

    has_change = limit is not None or enable or disable
    if has_change:
        status_ctx = (
            contextlib.nullcontext()
            if quiet
            else console.status("[cyan]Adjusting...", spinner="toggle12")
        )
        enabled: bool | None = None
        if enable:
            enabled = True
        elif disable:
            enabled = False

        with status_ctx:
            async with Peblar(host=host) as peblar:
                await peblar.login(password=password)
                await peblar.update_user_configuration(
                    PeblarSetUserConfiguration(
                        user_defined_household_power_limit=limit,
                        user_defined_household_power_limit_enabled=enabled,
                    ),
                )
        print_cli_success(quiet=quiet, message="✅[green]Success!")
        return

    async with Peblar(host=host) as peblar:
        await peblar.login(password=password)
        config = await peblar.user_configuration()

    table = Table(title="Peblar household power limit")
    table.add_column("Property", style="cyan bold")
    table.add_column("Value", style="bold")

    table.add_row(
        "Allowed",
        convert_to_string(config.user_defined_household_power_limit_allowed),
    )
    table.add_row(
        "Enabled",
        convert_to_string(config.user_defined_household_power_limit_enabled),
    )
    table.add_row(
        "Power limit",
        f"{round(config.user_defined_household_power_limit / 1000, 3)} kW"
        f" ({config.user_defined_household_power_limit} W)",
    )
    table.add_row("Source", config.user_defined_household_power_limit_source)

    console.print(table)


@cli.command("buzzer")
async def buzzer(
    host: Annotated[
        str,
        typer.Option(
            help="Peblar charger IP address or hostname",
            prompt="Host address",
            show_default=False,
            envvar="PEBLAR_HOST",
        ),
    ],
    password: Annotated[
        str,
        typer.Option(
            help="Peblar charger login password",
            prompt="Password",
            show_default=False,
            hide_input=True,
            envvar="PEBLAR_PASSWORD",
        ),
    ],
    volume: Annotated[
        SoundVolume,
        typer.Option(
            help="Buzzer volume level",
        ),
    ],
    quiet: Annotated[bool, QUIET_OPTION] = False,
) -> None:
    """Set the buzzer volume of the Peblar charger."""
    status_ctx = (
        contextlib.nullcontext()
        if quiet
        else console.status("[cyan]Adjusting...", spinner="toggle12")
    )
    with status_ctx:
        async with Peblar(host=host) as peblar:
            await peblar.login(password=password)
            await peblar.set_buzzer_volume(volume=volume)
    print_cli_success(quiet=quiet, message="✅[green]Success!")


@cli.command("led")
async def led(
    host: Annotated[
        str,
        typer.Option(
            help="Peblar charger IP address or hostname",
            prompt="Host address",
            show_default=False,
            envvar="PEBLAR_HOST",
        ),
    ],
    password: Annotated[
        str,
        typer.Option(
            help="Peblar charger login password",
            prompt="Password",
            show_default=False,
            hide_input=True,
            envvar="PEBLAR_PASSWORD",
        ),
    ],
    brightness: Annotated[
        LedBrightness,
        typer.Option(
            help="LED brightness level",
        ),
    ],
    quiet: Annotated[bool, QUIET_OPTION] = False,
) -> None:
    """Set the LED brightness of the Peblar charger."""
    status_ctx = (
        contextlib.nullcontext()
        if quiet
        else console.status("[cyan]Adjusting...", spinner="toggle12")
    )
    with status_ctx:
        async with Peblar(host=host) as peblar:
            await peblar.login(password=password)
            await peblar.set_led_brightness(brightness=brightness)
    print_cli_success(quiet=quiet, message="✅[green]Success!")


@cli.command("reboot")
async def reboot(
    host: Annotated[
        str,
        typer.Option(
            help="Peblar charger IP address or hostname",
            prompt="Host address",
            show_default=False,
            envvar="PEBLAR_HOST",
        ),
    ],
    password: Annotated[
        str,
        typer.Option(
            help="Peblar charger login password",
            prompt="Password",
            show_default=False,
            hide_input=True,
            envvar="PEBLAR_PASSWORD",
        ),
    ],
    quiet: Annotated[bool, QUIET_OPTION] = False,
) -> None:
    """Reboot the Peblar charger."""
    status_ctx = (
        contextlib.nullcontext()
        if quiet
        else console.status("[cyan]Rebooting...", spinner="toggle12")
    )
    with status_ctx:
        async with Peblar(host=host) as peblar:
            await peblar.login(password=password)
            await peblar.reboot()
    print_cli_success(quiet=quiet, message="✅[green]Success!")


@cli.command("update")
async def update(
    host: Annotated[
        str,
        typer.Option(
            help="Peblar charger IP address or hostname",
            prompt="Host address",
            show_default=False,
            envvar="PEBLAR_HOST",
        ),
    ],
    password: Annotated[
        str,
        typer.Option(
            help="Peblar charger login password",
            prompt="Password",
            show_default=False,
            hide_input=True,
            envvar="PEBLAR_PASSWORD",
        ),
    ],
    firmware: Annotated[
        bool,
        typer.Option(
            help="Update the firmware",
        ),
    ] = False,
    customization: Annotated[
        bool,
        typer.Option(
            help="Update the customization",
        ),
    ] = False,
    quiet: Annotated[bool, QUIET_OPTION] = False,
) -> None:
    """Update the Peblar charger."""
    if not firmware and not customization:
        msg = "At least one of --firmware or --customization must be used."
        raise typer.BadParameter(msg)
    if firmware and customization:
        msg = "--firmware cannot be used with --customization."
        raise typer.BadParameter(msg)

    status_ctx = (
        contextlib.nullcontext()
        if quiet
        else console.status("[cyan]Updating...", spinner="toggle12")
    )
    with status_ctx:
        async with Peblar(host=host) as peblar:
            await peblar.login(password=password)
            if firmware:
                await peblar.update(package_type=PackageType.FIRMWARE)
            if customization:
                await peblar.update(package_type=PackageType.CUSTOMIZATION)

    print_cli_success(quiet=quiet, message="✅[green]Success!")


@cli.command("api")
# pylint: disable=too-many-arguments,too-many-positional-arguments
async def rest_api(
    host: Annotated[
        str,
        typer.Option(
            help="Peblar charger IP address or hostname",
            prompt="Host address",
            show_default=False,
            envvar="PEBLAR_HOST",
        ),
    ],
    password: Annotated[
        str,
        typer.Option(
            help="Peblar charger login password",
            prompt="Password",
            show_default=False,
            hide_input=True,
            envvar="PEBLAR_PASSWORD",
        ),
    ],
    enable: Annotated[
        bool,
        typer.Option(
            help="Enable the local REST API",
        ),
    ] = False,
    disable: Annotated[
        bool,
        typer.Option(
            help="Disable the local REST API",
        ),
    ] = False,
    read: Annotated[
        bool,
        typer.Option(
            help="Set access mode to read-only",
        ),
    ] = False,
    write: Annotated[
        bool,
        typer.Option(
            help="Set access mode to read-write",
        ),
    ] = False,
    generate_new_token: Annotated[
        bool,
        typer.Option(
            help="Generate a new API token",
        ),
    ] = False,
    quiet: Annotated[bool, QUIET_OPTION] = False,
) -> None:
    """Control access to the Local REST API."""
    if enable and disable:
        msg = "--disable cannot be used with --enable."
        raise typer.BadParameter(msg)
    if read and write:
        msg = "--read cannot be used with --write."
        raise typer.BadParameter(msg)

    async with Peblar(host=host) as peblar:
        await peblar.login(password=password)
        if enable or disable or read or write or generate_new_token:
            status_ctx = (
                contextlib.nullcontext()
                if quiet
                else console.status("[cyan]Adjusting...", spinner="toggle12")
            )
            with status_ctx:
                if enable:
                    await peblar.rest_api(enable=True)
                if disable:
                    await peblar.rest_api(enable=False)
                if read:
                    await peblar.rest_api(access_mode=AccessMode.READ_ONLY)
                if write:
                    await peblar.rest_api(access_mode=AccessMode.READ_WRITE)
                if generate_new_token:
                    await peblar.api_token(generate_new_api_token=generate_new_token)
            print_cli_success(quiet=quiet, message="✅[green]Success!")
            if quiet:
                return

        config = await peblar.user_configuration()
        token = await peblar.api_token()

    table = Table(title="Peblar Local REST API configuration")
    table.add_column("Property", style="cyan bold")
    table.add_column("Value", style="bold")

    table.add_row(
        "Local REST API enabled", convert_to_string(config.local_rest_api_enabled)
    )
    table.add_row("Local REST API access mode", config.local_rest_api_access_mode.value)
    table.add_row("Local REST API token", token)
    console.print(table)


@cli.command("modbus")
# pylint: disable=too-many-arguments,too-many-positional-arguments
async def modbus(
    host: Annotated[
        str,
        typer.Option(
            help="Peblar charger IP address or hostname",
            prompt="Host address",
            show_default=False,
            envvar="PEBLAR_HOST",
        ),
    ],
    password: Annotated[
        str,
        typer.Option(
            help="Peblar charger login password",
            prompt="Password",
            show_default=False,
            hide_input=True,
            envvar="PEBLAR_PASSWORD",
        ),
    ],
    enable: Annotated[
        bool,
        typer.Option(
            help="Enable the Modbus API",
        ),
    ] = False,
    disable: Annotated[
        bool,
        typer.Option(
            help="Disable the Modbus API",
        ),
    ] = False,
    read: Annotated[
        bool,
        typer.Option(
            help="Set access mode to read-only",
        ),
    ] = False,
    write: Annotated[
        bool,
        typer.Option(
            help="Set access mode to read-write",
        ),
    ] = False,
    quiet: Annotated[bool, QUIET_OPTION] = False,
) -> None:
    """Control access to the Modbus API."""
    if enable and disable:
        msg = "--disable cannot be used with --enable."
        raise typer.BadParameter(msg)
    if read and write:
        msg = "--read cannot be used with --write."
        raise typer.BadParameter(msg)

    async with Peblar(host=host) as peblar:
        await peblar.login(password=password)
        if enable or disable or read or write:
            status_ctx = (
                contextlib.nullcontext()
                if quiet
                else console.status("[cyan]Adjusting...", spinner="toggle12")
            )
            with status_ctx:
                if enable:
                    await peblar.modbus_api(enable=True)
                if disable:
                    await peblar.modbus_api(enable=False)
                if read:
                    await peblar.modbus_api(access_mode=AccessMode.READ_ONLY)
                if write:
                    await peblar.modbus_api(access_mode=AccessMode.READ_WRITE)
            print_cli_success(quiet=quiet, message="✅[green]Success!")
            if quiet:
                return
        config = await peblar.user_configuration()

    table = Table(title="Peblar Modbus API configuration")
    table.add_column("Property", style="cyan bold")
    table.add_column("Value", style="bold")

    table.add_row("Modbus API enabled", convert_to_string(config.modbus_server_enabled))
    table.add_row("Modbus API access mode", config.modbus_server_access_mode.value)

    console.print(table)


@cli.command("info")
async def system_information(
    host: Annotated[
        str,
        typer.Option(
            help="Peblar charger IP address or hostname",
            prompt="Host address",
            show_default=False,
            envvar="PEBLAR_HOST",
        ),
    ],
    password: Annotated[
        str,
        typer.Option(
            help="Peblar charger login password",
            prompt="Password",
            show_default=False,
            hide_input=True,
            envvar="PEBLAR_PASSWORD",
        ),
    ],
    quiet: Annotated[bool, QUIET_OPTION] = False,  # noqa: ARG001  # pylint: disable=unused-argument
) -> None:
    """List information about the Peblar charger."""
    async with Peblar(host=host) as peblar:
        await peblar.login(password=password)
        info = await peblar.system_information()

    table = Table(title="Peblar charger information")
    table.add_column("Property", style="cyan bold")
    table.add_column("Value", style="bold")

    table.add_row("Customer ID", info.customer_id)
    table.add_row("Ethernet MAC address", info.ethernet_mac_address)
    table.add_row("Firmware version", info.firmware_version)
    table.add_row(
        "Hardware fixed cable rating",
        f"{info.hardware_fixed_cable_rating}A"
        if info.hardware_fixed_cable_rating is not None
        else "N/A (socket charger)",
    )
    table.add_row("Hardware has BOP", convert_to_string(info.hardware_has_bop))
    table.add_row("Hardware has buzzer", convert_to_string(info.hardware_has_buzzer))
    table.add_row(
        "Hardware has Eichrecht laser marking",
        convert_to_string(info.hardware_has_eichrecht_laser_marking),
    )
    table.add_row(
        "Hardware has Ethernet", convert_to_string(info.hardware_has_ethernet)
    )
    table.add_row("Hardware has LED", convert_to_string(info.hardware_has_led))
    table.add_row("Hardware has LTE", convert_to_string(info.hardware_has_lte))
    table.add_row(
        "Hardware has meter display", convert_to_string(info.hardware_has_meter_display)
    )
    table.add_row("Hardware has meter", convert_to_string(info.hardware_has_meter))
    table.add_row("Hardware has PLC", convert_to_string(info.hardware_has_plc))
    table.add_row("Hardware has RFID", convert_to_string(info.hardware_has_rfid))
    table.add_row("Hardware has RS485", convert_to_string(info.hardware_has_rs485))
    table.add_row("Hardware has socket", convert_to_string(info.hardware_has_socket))
    table.add_row("Hardware has TPM", convert_to_string(info.hardware_has_tpm))
    table.add_row("Hardware has WLAN", convert_to_string(info.hardware_has_wlan))
    table.add_row("Hardware max current", f"{info.hardware_max_current}A")
    table.add_row(
        "Hardware one or three phase",
        convert_to_string(info.hardware_one_or_three_phase),
    )
    table.add_row("Hostname", info.hostname)
    table.add_row("Mainboard part number", info.mainboard_part_number)
    table.add_row("Mainboard serial number", info.mainboard_serial_number)
    table.add_row("Meter firmware version", info.meter_firmware_version)
    table.add_row("Product model name", info.product_model_name)
    table.add_row("Product number", info.product_number)
    table.add_row("Product serial number", info.product_serial_number)
    table.add_row("Product vendor name", info.product_vendor_name)
    table.add_row("WLAN AP MAC address", info.wlan_ap_mac_address)
    table.add_row("WLAN MAC address", info.wlan_mac_address)

    console.print(table)


@cli.command("config")
async def user_configuration(  # pylint: disable=too-many-statements
    host: Annotated[
        str,
        typer.Option(
            help="Peblar charger IP address or hostname",
            prompt="Host address",
            show_default=False,
            envvar="PEBLAR_HOST",
        ),
    ],
    password: Annotated[
        str,
        typer.Option(
            help="Peblar charger login password",
            prompt="Password",
            show_default=False,
            hide_input=True,
            envvar="PEBLAR_PASSWORD",
        ),
    ],
    charge_current_limit: Annotated[
        int | None,
        typer.Option(
            help="Set user-defined charge limit (A), minimum 6",
            show_default=False,
        ),
    ] = None,
    quiet: Annotated[bool, QUIET_OPTION] = False,
) -> None:
    """Show or change the user configuration."""
    if charge_current_limit is not None and charge_current_limit < 6:
        msg = "User-defined charge limit current must be at least 6A."
        raise typer.BadParameter(msg)

    async with Peblar(host=host) as peblar:
        await peblar.login(password=password)
        if charge_current_limit is not None:
            await peblar.update_user_configuration(
                PeblarSetUserConfiguration(
                    user_defined_charge_limit_current=charge_current_limit,
                ),
            )
            print_cli_success(quiet=quiet, message="Success!")
            return
        config = await peblar.user_configuration()

    table = Table(title="Peblar user configuration")
    table.add_column("Property", style="cyan bold")
    table.add_column("Value", style="bold")

    table.add_row(
        "BOP fallback current", convert_to_string(config.bop_fallback_current)
    )
    table.add_row("BOP HomeWizard address", config.bop_home_wizard_address)
    table.add_row(
        "BOP source parameters", convert_to_string(config.bop_source_parameters)
    )
    table.add_row("BOP source", config.bop_source)
    table.add_row("Buzzer volume", convert_to_string(config.buzzer_volume))
    table.add_row("Connected phases", convert_to_string(config.connected_phases))
    table.add_row("Current control BOP CT type", config.current_control_bop_ct_type)
    table.add_row(
        "Current control BOP enabled",
        convert_to_string(config.current_control_bop_enabled),
    )
    table.add_row(
        "Current control BOP fuse rating",
        f"{config.current_control_bop_fuse_rating}A",
    )
    table.add_row(
        "Current control fixed charge current limit",
        convert_to_string(config.current_control_fixed_charge_current_limit),
    )
    table.add_row("Ground monitoring", convert_to_string(config.ground_monitoring))
    table.add_row(
        "Group load balancing enabled",
        convert_to_string(config.group_load_balancing_enabled),
    )
    table.add_row(
        "Group load balancing fallback current",
        f"{config.group_load_balancing_fallback_current}A",
    )
    table.add_row(
        "Group load balancing group ID",
        convert_to_string(config.group_load_balancing_group_id),
    )
    table.add_row(
        "Group load balancing interface", config.group_load_balancing_interface
    )
    table.add_row(
        "Group load balancing max current",
        f"{config.group_load_balancing_max_current}A",
    )
    table.add_row("Group load balancing role", config.group_load_balancing_role)
    table.add_row(
        "LED intensity manual", convert_to_string(config.led_intensity_manual)
    )
    table.add_row("LED intensity max", convert_to_string(config.led_intensity_max))
    table.add_row("LED intensity min", convert_to_string(config.led_intensity_min))
    table.add_row("LED intensity mode", config.led_intensity_mode)
    table.add_row("Local REST API access mode", config.local_rest_api_access_mode)
    table.add_row(
        "Local REST API allowed", convert_to_string(config.local_rest_api_allowed)
    )
    table.add_row(
        "Local REST API enabled", convert_to_string(config.local_rest_api_enabled)
    )
    table.add_row(
        "Local smart charging allowed",
        convert_to_string(config.local_smart_charging_allowed),
    )
    table.add_row("Modbus server access mode", config.modbus_server_access_mode)
    table.add_row(
        "Modbus server allowed", convert_to_string(config.modbus_server_allowed)
    )
    table.add_row(
        "Modbus server enabled", convert_to_string(config.modbus_server_enabled)
    )
    table.add_row("Phase rotation", config.phase_rotation)
    table.add_row(
        "Power limit input DI1 inverse",
        convert_to_string(config.power_limit_input_di1_inverse),
    )
    table.add_row(
        "Power limit input DI1 limit",
        f"{config.power_limit_input_di1_limit}A",
    )
    table.add_row(
        "Power limit input DI2 inverse",
        convert_to_string(config.power_limit_input_di2_inverse),
    )
    table.add_row(
        "Power limit input DI2 limit", f"{config.power_limit_input_di2_limit}A"
    )
    table.add_row(
        "Power limit input enabled", convert_to_string(config.power_limit_input_enabled)
    )
    table.add_row("Predefined CPO name", config.predefined_cpo_name)
    table.add_row(
        "Scheduled charging allowed",
        convert_to_string(config.scheduled_charging_allowed),
    )
    table.add_row(
        "Scheduled charging enabled",
        convert_to_string(config.scheduled_charging_enabled),
    )
    table.add_row("SECC OCPP active", convert_to_string(config.secc_ocpp_active))
    table.add_row("SECC OCPP URI", config.secc_ocpp_uri)
    table.add_row(
        "Session manager charge without authentication",
        convert_to_string(config.session_manager_charge_without_authentication),
    )
    table.add_row(
        "Solar charging allowed", convert_to_string(config.solar_charging_allowed)
    )
    table.add_row(
        "Solar charging enabled", convert_to_string(config.solar_charging_enabled)
    )
    table.add_row("Solar charging mode", config.solar_charging_mode)
    table.add_row(
        "Solar charging source parameters",
        convert_to_string(config.solar_charging_source_parameters),
    )
    table.add_row("Solar charging source", config.solar_charging_source)
    table.add_row("Time zone", config.time_zone)
    table.add_row(
        "User defined charge limit current allowed",
        convert_to_string(config.user_defined_charge_limit_current_allowed),
    )
    table.add_row(
        "User defined charge limit current",
        f"{config.user_defined_charge_limit_current}A",
    )
    table.add_row(
        "User defined household power limit allowed",
        convert_to_string(config.user_defined_household_power_limit_allowed),
    )
    table.add_row(
        "User defined household power limit enabled",
        convert_to_string(config.user_defined_household_power_limit_enabled),
    )
    table.add_row(
        "User defined household power limit source",
        config.user_defined_household_power_limit_source,
    )
    table.add_row(
        "User defined household power limit",
        f"{round(config.user_defined_household_power_limit / 1000, 3)} kW",
    )
    table.add_row(
        "User keep socket locked", convert_to_string(config.user_keep_socket_locked)
    )
    table.add_row(
        "VDE phase imbalance enabled",
        convert_to_string(config.vde_phase_imbalance_enabled),
    )
    table.add_row("VDE phase imbalance limit", f"{config.vde_phase_imbalance_limit}A")
    table.add_row(
        "Web IF update helper", convert_to_string(config.web_if_update_helper)
    )

    table.add_section()
    smart_charging_mode = "Unknown"
    if config.smart_charging is not None:
        smart_charging_mode = {
            SmartChargingMode.DEFAULT: "Default",
            SmartChargingMode.FAST_SOLAR: "Fast solar",
            SmartChargingMode.SMART_SOLAR: "Smart solar",
            SmartChargingMode.PURE_SOLAR: "Pure solar",
            SmartChargingMode.SCHEDULED: "Scheduled",
        }.get(config.smart_charging, "Unknown")
    table.add_row("Smart charging mode", smart_charging_mode)

    console.print(table)


@cli.command("smart-charging")
# pylint: disable=too-many-arguments,too-many-positional-arguments
async def smart_charging(
    host: Annotated[
        str,
        typer.Option(
            help="Peblar charger IP address or hostname",
            prompt="Host address",
            show_default=False,
            envvar="PEBLAR_HOST",
        ),
    ],
    password: Annotated[
        str,
        typer.Option(
            help="Peblar charger login password",
            prompt="Password",
            show_default=False,
            hide_input=True,
            envvar="PEBLAR_PASSWORD",
        ),
    ],
    default: Annotated[
        bool,
        typer.Option(
            help="Not limited by any strategy.",
        ),
    ] = False,
    fast_solar: Annotated[
        bool,
        typer.Option(
            help="Fast charge with a mix of grid and solar power.",
        ),
    ] = False,
    smart_solar: Annotated[
        bool,
        typer.Option(
            help="Charge with a smart mix of grid and solar power.",
        ),
    ] = False,
    pure_solar: Annotated[
        bool,
        typer.Option(
            help="Charge only with solar power.",
        ),
    ] = False,
    scheduled: Annotated[
        bool,
        typer.Option(
            help="Scheduled charging.",
        ),
    ] = False,
    quiet: Annotated[bool, QUIET_OPTION] = False,
) -> None:
    """Control the smart charging mode."""
    # Only one of the charging modes can be selected, and at least one must be selected.
    if sum([default, fast_solar, smart_solar, pure_solar, scheduled]) != 1 or not any(
        [default, fast_solar, smart_solar, pure_solar, scheduled]
    ):
        msg = (
            "Exactly one of --default, --fast-solar, --smart-solar, "
            "--pure-solar or --scheduled must be used."
        )
        raise typer.BadParameter(msg)

    status_ctx = (
        contextlib.nullcontext()
        if quiet
        else console.status("[cyan]Adjusting...", spinner="toggle12")
    )
    with status_ctx:
        async with Peblar(host=host) as peblar:
            await peblar.login(password=password)
            if default:
                await peblar.smart_charging(SmartChargingMode.DEFAULT)
            if fast_solar:
                await peblar.smart_charging(SmartChargingMode.FAST_SOLAR)
            if smart_solar:
                await peblar.smart_charging(SmartChargingMode.SMART_SOLAR)
            if pure_solar:
                await peblar.smart_charging(SmartChargingMode.PURE_SOLAR)
            if scheduled:
                await peblar.smart_charging(SmartChargingMode.SCHEDULED)

    print_cli_success(quiet=quiet, message="✅[green]Success!")


@cli.command("rfid-tokens")
async def rfid_tokens(
    host: Annotated[
        str,
        typer.Option(
            help="Peblar charger IP address or hostname",
            prompt="Host address",
            show_default=False,
            envvar="PEBLAR_HOST",
        ),
    ],
    password: Annotated[
        str,
        typer.Option(
            help="Peblar charger login password",
            prompt="Password",
            show_default=False,
            hide_input=True,
            envvar="PEBLAR_PASSWORD",
        ),
    ],
    quiet: Annotated[bool, QUIET_OPTION] = False,  # noqa: ARG001  # pylint: disable=unused-argument
) -> None:
    """List RFID tokens in the standalone auth list."""
    async with Peblar(host=host) as peblar:
        await peblar.login(password=password)
        tokens = await peblar.rfid_tokens()

    table = Table(title="Peblar RFID tokens")
    table.add_column("UID", style="cyan bold")
    table.add_column("Description", style="cyan bold")

    for token in tokens:
        table.add_row(token.rfid_token_uid, token.rfid_token_description)

    console.print(table)


@cli.command("add-rfid-token")
async def add_rfid_token(
    host: Annotated[
        str,
        typer.Option(
            help="Peblar charger IP address or hostname",
            prompt="Host address",
            show_default=False,
            envvar="PEBLAR_HOST",
        ),
    ],
    password: Annotated[
        str,
        typer.Option(
            help="Peblar charger login password",
            prompt="Password",
            show_default=False,
            hide_input=True,
            envvar="PEBLAR_PASSWORD",
        ),
    ],
    uid: Annotated[
        str,
        typer.Option(
            help="RFID token UID",
            prompt="UID",
            show_default=False,
        ),
    ],
    description: Annotated[
        str,
        typer.Option(
            help="RFID token description",
            prompt="Description",
            show_default=False,
        ),
    ],
    quiet: Annotated[bool, QUIET_OPTION] = False,
) -> None:
    """Add an RFID token to the standalone auth list."""
    status_ctx = (
        contextlib.nullcontext()
        if quiet
        else console.status("[cyan]Adding RFID token...", spinner="toggle12")
    )
    with status_ctx:
        async with Peblar(host=host) as peblar:
            await peblar.login(password=password)
            await peblar.add_rfid_token(
                rfid_token_uid=uid,
                rfid_token_description=description,
            )
    print_cli_success(quiet=quiet, message="✅[green]Success!")


@cli.command("del-rfid-token")
async def del_rfid_token(
    host: Annotated[
        str,
        typer.Option(
            help="Peblar charger IP address or hostname",
            prompt="Host address",
            show_default=False,
            envvar="PEBLAR_HOST",
        ),
    ],
    password: Annotated[
        str,
        typer.Option(
            help="Peblar charger login password",
            prompt="Password",
            show_default=False,
            hide_input=True,
            envvar="PEBLAR_PASSWORD",
        ),
    ],
    uid: Annotated[
        str,
        typer.Option(
            help="RFID token UID to remove",
            prompt="UID",
        ),
    ],
    quiet: Annotated[bool, QUIET_OPTION] = False,
) -> None:
    """Remove an RFID token from the standalone auth list."""
    status_ctx = (
        contextlib.nullcontext()
        if quiet
        else console.status("[cyan]Removing RFID token...", spinner="toggle12")
    )
    with status_ctx:
        async with Peblar(host=host) as peblar:
            await peblar.login(password=password)
            await peblar.delete_rfid_token(uid=uid)
    print_cli_success(quiet=quiet, message="✅[green]Success!")


@cli.command("ev")
async def ev(
    host: Annotated[
        str,
        typer.Option(
            help="Peblar charger IP address or hostname",
            prompt="Host address",
            show_default=False,
            envvar="PEBLAR_HOST",
        ),
    ],
    password: Annotated[
        str,
        typer.Option(
            help="Peblar charger login password",
            prompt="Password",
            show_default=False,
            hide_input=True,
            envvar="PEBLAR_PASSWORD",
        ),
    ],
    charge_limit: Annotated[
        int | None,
        typer.Option(
            help="Charge current limit in A",
        ),
    ] = None,
    force_single_phase: Annotated[
        bool | None,
        typer.Option(
            help="Force single phase charging",
        ),
    ] = None,
    quiet: Annotated[bool, QUIET_OPTION] = False,
) -> None:
    """Get the EV interface status of the Peblar charger."""
    async with Peblar(host=host) as peblar:
        await peblar.login(password=password)
        async with await peblar.rest_api() as api:
            if charge_limit is not None or force_single_phase is not None:
                status_ctx = (
                    contextlib.nullcontext()
                    if quiet
                    else console.status("[cyan]Adjusting...", spinner="toggle12")
                )
                with status_ctx:
                    await api.ev_interface(
                        charge_current_limit=charge_limit * 1000
                        if charge_limit is not None
                        else None,
                        force_single_phase=force_single_phase,
                    )
                print_cli_success(quiet=quiet, message="✅[green]Success")
                if quiet:
                    return

            ev_interface = await api.ev_interface()

    table = Table(title="Peblar EV interface information")
    table.add_column("Property", style="cyan bold")
    table.add_column("Value", style="bold")

    table.add_row(
        "Charge current limit",
        f"{round(ev_interface.charge_current_limit / 1000, 3)}A",
    )
    table.add_row(
        "Charge current limit actual",
        f"{round(ev_interface.charge_current_limit_actual / 1000, 3)}A",
    )
    table.add_row(
        "Charge current limit source", ev_interface.charge_current_limit_source
    )

    cp_state = {
        CPState.NO_EV_CONNECTED: "EV not connected",
        CPState.CHARGING_SUSPENDED: "Charging suspended",
        CPState.CHARGING: "Charging",
        CPState.CHARGING_VENTILATION: "Charging, ventilation requested",
        CPState.ERROR: "Error; short or powered off",
        CPState.FAULT: "Fault; Charger is not operational",
        CPState.INVALID: "Invalid; Charger is not operational",
    }.get(ev_interface.cp_state, "Unknown")

    table.add_row("CP state", cp_state)
    table.add_row(
        "Force single phase", convert_to_string(ev_interface.force_single_phase)
    )

    console.print(table)


@cli.command("health")
async def health(
    host: Annotated[
        str,
        typer.Option(
            help="Peblar charger IP address or hostname",
            prompt="Host address",
            show_default=False,
            envvar="PEBLAR_HOST",
        ),
    ],
    password: Annotated[
        str,
        typer.Option(
            help="Peblar charger login password",
            prompt="Password",
            show_default=False,
            hide_input=True,
            envvar="PEBLAR_PASSWORD",
        ),
    ],
    quiet: Annotated[bool, QUIET_OPTION] = False,  # noqa: ARG001  # pylint: disable=unused-argument
) -> None:
    """Get the health status of the Peblar charger."""
    async with Peblar(host=host) as peblar:
        await peblar.login(password=password)
        async with await peblar.rest_api() as api:
            data = await api.health()

    table = Table(title="Peblar API Health")
    table.add_column("Property", style="cyan bold")
    table.add_column("Value", style="bold")

    table.add_row("API Access mode", data.access_mode.value)
    table.add_row("API version", convert_to_string(data.api_version))
    console.print(table)


@cli.command("meter")
async def meter(
    host: Annotated[
        str,
        typer.Option(
            help="Peblar charger IP address or hostname",
            prompt="Host address",
            show_default=False,
            envvar="PEBLAR_HOST",
        ),
    ],
    password: Annotated[
        str,
        typer.Option(
            help="Peblar charger login password",
            prompt="Password",
            show_default=False,
            hide_input=True,
            envvar="PEBLAR_PASSWORD",
        ),
    ],
    quiet: Annotated[bool, QUIET_OPTION] = False,  # noqa: ARG001  # pylint: disable=unused-argument
) -> None:
    """Get meter status of the Peblar charger."""
    async with Peblar(host=host) as peblar:
        await peblar.login(password=password)
        async with await peblar.rest_api() as api:
            meter_data = await api.meter()

    table = Table(title="Peblar meter status")
    table.add_column("Property", style="cyan bold")
    table.add_column("Value", style="bold")

    table.add_row("Energy session", f"{round(meter_data.energy_session / 1000, 3)}kWh")
    table.add_row("Energy total", f"{round(meter_data.energy_total / 1000, 3)}kWh")

    table.add_section()

    table.add_row("Total power", f"{meter_data.power_total}W")
    table.add_row("Power phase 1", f"{meter_data.power_phase_1}W")
    table.add_row("Power phase 2", f"{meter_data.power_phase_2}W")
    table.add_row("Power phase 3", f"{meter_data.power_phase_3}W")

    table.add_section()

    total_current = round(
        (
            meter_data.current_phase_1
            + meter_data.current_phase_2
            + meter_data.current_phase_3
        )
        / 1000,
        3,
    )
    table.add_row("Total current", f"{total_current}A")
    table.add_row("Current Phase 1", f"{round(meter_data.current_phase_1 / 1000, 3)}A")
    table.add_row("Current Phase 2", f"{round(meter_data.current_phase_2 / 1000, 3)}A")
    table.add_row("Current Phase 3", f"{round(meter_data.current_phase_3 / 1000, 3)}A")

    table.add_section()

    table.add_row("Voltage Phase 1", f"{meter_data.voltage_phase_1 or 0}V")
    table.add_row("Voltage Phase 2", f"{meter_data.voltage_phase_2 or 0}V")
    table.add_row("Voltage Phase 3", f"{meter_data.voltage_phase_3 or 0}V")

    console.print(table)


@cli.command("meterhistory")
# pylint: disable-next=too-many-arguments
async def meterhistory(
    *,
    host: Annotated[
        str,
        typer.Option(
            help="Peblar charger IP address or hostname",
            prompt="Host address",
            show_default=False,
            envvar="PEBLAR_HOST",
        ),
    ],
    password: Annotated[
        str,
        typer.Option(
            help="Peblar charger login password",
            prompt="Password",
            show_default=False,
            hide_input=True,
            envvar="PEBLAR_PASSWORD",
        ),
    ],
    start: Annotated[
        str | None,
        typer.Option(
            help="Optional start time in UTC ISO format, e.g. 2026-03-17T23:00:00Z",
        ),
    ] = None,
    stop: Annotated[
        str | None,
        typer.Option(
            help="Optional stop time in UTC ISO format, e.g. 2026-03-18T22:59:59Z",
        ),
    ] = None,
    filename: Annotated[
        str | None,
        typer.Option(
            help="Optional output CSV filename (only with --export)",
        ),
    ] = None,
    export: Annotated[
        bool,
        typer.Option(
            "--export",
            help="Write meter history to a CSV file; default is summary only",
        ),
    ] = False,
    quiet: Annotated[bool, QUIET_OPTION] = False,
) -> None:
    """Show meter history summary, or export to CSV with --export."""
    status_msg = (
        "[cyan]Generating meter history CSV..."
        if export
        else "[cyan]Loading meter history..."
    )
    status_ctx = (
        contextlib.nullcontext()
        if quiet
        else console.status(status_msg, spinner="toggle12")
    )

    with status_ctx:
        async with Peblar(host=host) as peblar:
            await peblar.login(password=password)
            await meterhistory_run_with_client(
                peblar,
                options=MeterHistoryCliOptions(
                    start=start,
                    stop=stop,
                    filename=filename,
                    export=export,
                    quiet=quiet,
                ),
            )


@cli.command("system")
async def system(
    host: Annotated[
        str,
        typer.Option(
            help="Peblar charger IP address or hostname",
            prompt="Host address",
            show_default=False,
            envvar="PEBLAR_HOST",
        ),
    ],
    password: Annotated[
        str,
        typer.Option(
            help="Peblar charger login password",
            prompt="Password",
            show_default=False,
            hide_input=True,
            envvar="PEBLAR_PASSWORD",
        ),
    ],
    quiet: Annotated[bool, QUIET_OPTION] = False,  # noqa: ARG001  # pylint: disable=unused-argument
) -> None:
    """Get the status of the Peblar charger."""
    async with Peblar(host=host) as peblar:
        await peblar.login(password=password)
        async with await peblar.rest_api() as api:
            data = await api.system()

    table = Table(title="Peblar charger system status")
    table.add_column("Property", style="cyan bold")
    table.add_column("Value", style="bold")

    table.add_row(
        "Active error codes", ",".join(data.active_error_codes) or "No errors"
    )
    table.add_row(
        "Active warning codes", ",".join(data.active_warning_codes) or "No warnings"
    )

    table.add_section()
    table.add_row("Phase count", convert_to_string(data.phase_count))
    table.add_row(
        "Force of single phase allowed",
        convert_to_string(data.force_single_phase_allowed),
    )

    table.add_section()
    table.add_row("Firmware version", data.firmware_version)
    table.add_row("Product serial number", data.product_serial_number)
    table.add_row("Product part number", data.product_part_number)

    table.add_section()
    table.add_row("Uptime", f"{data.uptime} seconds")
    if data.wlan_signal_strength is not None:
        table.add_row("WLAN signal strength", f"{data.wlan_signal_strength} dBm")
    else:
        table.add_row("WLAN signal strength", "WLAN not connected")
    if data.cellular_signal_strength is not None:
        table.add_row(
            "Cellular signal strength", f"{data.cellular_signal_strength} dBm"
        )
    else:
        table.add_row("Cellular signal strength", "Cellular not connected")

    console.print(table)


@cli.command("scan")
async def scan(
    quiet: Annotated[bool, QUIET_OPTION] = False,
) -> None:
    """Scan for Peblar chargers on the network.

    Browses both the Peblar REST API service (_pblr._tcp, firmware 1.8+)
    and the legacy HTTP service (_http._tcp, older firmware). Legacy HTTP
    results are filtered by the PBLR- hostname prefix. Results from both
    service types are merged and deduplicated.
    """
    zeroconf = AsyncZeroconf()
    background_tasks: set[asyncio.Future[None]] = set()
    seen: set[str] = set()

    table = Table(
        title="\n\nFound Peblar chargers", header_style="cyan bold", show_lines=True
    )
    table.add_column("Addresses")
    table.add_column("Serial number")
    table.add_column("Software version")

    def async_on_service_state_change(
        zeroconf: Zeroconf,
        service_type: str,
        name: str,
        state_change: ServiceStateChange,
    ) -> None:
        """Handle service state changes."""
        if state_change is not ServiceStateChange.Added:
            return

        future = asyncio.ensure_future(
            async_display_service_info(zeroconf, service_type, name)
        )
        background_tasks.add(future)
        future.add_done_callback(background_tasks.discard)

    async def async_display_service_info(
        zeroconf: Zeroconf, service_type: str, name: str
    ) -> None:
        """Retrieve and display service info."""
        info = AsyncServiceInfo(service_type, name)
        if not await info.async_request(zeroconf, 3000) or not info.server:
            return

        # _pblr._tcp is Peblar-specific (firmware 1.8+), no extra filtering.
        # _http._tcp is generic; only accept chargers with PBLR- hostnames.
        is_pblr_service = service_type == "_pblr._tcp.local."
        if not is_pblr_service and not str(info.server).startswith("PBLR-"):
            return

        # Deduplicate by hostname, which is the one constant across both
        # _pblr._tcp and _http._tcp for the same charger.
        hostname = str(info.server).rstrip(".")
        if hostname in seen:
            return
        seen.add(hostname)

        props = info.properties or {}
        serial = props[b"sn"].decode() if b"sn" in props else ""  # ty: ignore[unresolved-attribute]
        version = props[b"version"].decode() if b"version" in props else ""  # ty: ignore[unresolved-attribute]

        if not quiet:
            console.print(
                f"[cyan bold]Found service {info.server}: is a Peblar charger 🎉"
            )

        table.add_row(
            f"{hostname}\n" + ", ".join(info.parsed_scoped_addresses()),
            serial or "N/A",
            version or "N/A",
        )

    if not quiet:
        console.print("[green]Scanning for Peblar chargers...")
        console.print("[red]Press Ctrl-C to exit\n")

    with Live(table, console=console, refresh_per_second=4):
        browser = AsyncServiceBrowser(
            zeroconf.zeroconf,
            ["_pblr._tcp.local.", "_http._tcp.local."],
            handlers=[async_on_service_state_change],
        )

        try:
            while True:  # noqa: ASYNC110
                await asyncio.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            if not quiet:
                console.print("\n[green]Control-C pressed, stopping scan")
            await browser.async_cancel()
            await asyncio.gather(*background_tasks, return_exceptions=True)
            await zeroconf.async_close()


# Keys whose values are replaced wholesale when anonymizing.
_REDACT_MAP: dict[str, str] = {
    "ApiToken": "0" * 64,
    "CustomCustomerId": "",
    "CustomerId": "PBLR-0000001",
    "CustomerUpdatePackagePubKey": "<redacted>",
    "Hostname": "PBLR-0000001",
}

# Keys that hold MAC addresses (anonymized to sequential fake MACs).
_MAC_KEYS = frozenset(
    {
        "EthMacAddr",
        "WlanApMacAddr",
        "WlanStaMacAddr",
    }
)

# Keys that hold serial numbers / part numbers.
_SERIAL_KEYS = frozenset({"MainboardSn", "ProductSn"})
_PART_NUMBER_KEYS = frozenset({"MainboardPn", "ProductPn"})

# Keys that hold network addresses or URIs that could leak device topology.
_ADDRESS_KEYS = frozenset({"BopHomeWizardAddress", "SeccOcppUri"})

# Keys containing JSON-encoded parameter strings that may embed device
# addresses (e.g. ``{"address":"p1meter-093586"}``).
_JSON_PARAM_KEYS = frozenset(
    {
        "BopSourceParameters",
        "SolarChargingSourceParameters",
        "UserDefinedHouseholdPowerLimitSourceParameters",
    }
)


def _anonymize(data: dict[str, object]) -> dict[str, object]:
    """Strip personally identifiable or device-unique fields from a response.

    Matching is done by key name so the function works across different
    chargers and firmware versions. Unknown keys are passed through unchanged.
    """
    mac_counter = 0
    result: dict[str, object] = {}

    for key, original in data.items():
        if key in _REDACT_MAP:
            result[key] = _REDACT_MAP[key]
        elif key in _MAC_KEYS:
            mac_counter += 1
            result[key] = f"AA:BB:CC:DD:EE:{mac_counter:02X}"
        elif key in _SERIAL_KEYS:
            result[key] = "00-00-AAA-000"
        elif key in _PART_NUMBER_KEYS:
            result[key] = "0000-0000-0000"
        elif key in _ADDRESS_KEYS:
            result[key] = ""
        elif key in _JSON_PARAM_KEYS and isinstance(original, str):
            result[key] = _anonymize_json_params(original)
        else:
            result[key] = original

    return result


def _anonymize_json_params(value: str) -> str:
    """Redact address fields inside a JSON-encoded parameter string."""
    try:
        params = json.loads(value)
        if isinstance(params, dict):
            for param_key in params:
                if "address" in param_key.lower():
                    params[param_key] = "redacted-host"
            return json.dumps(params)
    except (json.JSONDecodeError, TypeError):
        pass
    return value


@cli.command("dump")
async def dump(  # noqa: PLR0913
    host: Annotated[
        str,
        typer.Option(
            help="Peblar charger IP address or hostname",
            prompt="Host address",
            show_default=False,
            envvar="PEBLAR_HOST",
        ),
    ],
    password: Annotated[
        str,
        typer.Option(
            help="Peblar charger login password",
            prompt="Password",
            show_default=False,
            hide_input=True,
            envvar="PEBLAR_PASSWORD",
        ),
    ],
    output: Annotated[
        Path,
        typer.Option(
            help="Directory to write JSON fixtures into",
        ),
    ] = Path("dump"),
    raw: Annotated[
        bool,
        typer.Option(
            help="Skip anonymization and write raw charger responses",
        ),
    ] = False,
    quiet: Annotated[bool, QUIET_OPTION] = False,
) -> None:
    """Dump API responses from the charger as JSON fixture files.

    Connects to the charger, fetches every available endpoint, and writes
    the responses as pretty-printed JSON files into the output directory.
    Useful for capturing real-world responses for the test suite.

    By default, sensitive fields (serial numbers, MAC addresses, API tokens,
    public keys, network addresses) are anonymized. Pass --raw to keep the
    original values for personal debugging.

    The Local REST API endpoints are only dumped when the API is enabled
    on the charger.
    """
    output.mkdir(parents=True, exist_ok=True)

    def _write(name: str, data: str) -> None:
        path = output / name
        parsed = json.loads(data)
        if not raw:
            parsed = _anonymize(parsed)
        path.write_text(json.dumps(parsed, indent=2) + "\n")
        if not quiet:
            console.print(f"  [green]Wrote[/green] {path}")

    async with Peblar(host=host) as peblar:
        await peblar.login(password=password)

        if not quiet:
            console.print("[cyan bold]Dumping main API endpoints...")

        _write(
            "system_information.json",
            await peblar.request(URL("system/info")),
        )
        _write(
            "user_configuration.json",
            await peblar.request(URL("config/user")),
        )
        _write(
            "versions_current.json",
            await peblar.request(
                URL("system/software/automatic-update/current-versions"),
            ),
        )
        _write(
            "versions_available.json",
            await peblar.request(
                URL("system/software/automatic-update/available-versions"),
            ),
        )
        _write(
            "api_token.json",
            await peblar.request(URL("config/api-token")),
        )

        # Local REST API endpoints (only available when enabled)
        if not quiet:
            console.print("\n[cyan bold]Dumping Local REST API endpoints...")
        try:
            async with await peblar.rest_api() as api:
                _write("health.json", await api.request(URL("health")))
                _write("system.json", await api.request(URL("system")))
                _write("meter.json", await api.request(URL("meter")))
                _write("ev_interface.json", await api.request(URL("evinterface")))
        except PeblarConnectionError:
            if not quiet:
                console.print("  [yellow]Skipped (could not connect to REST API)")
        except PeblarError:
            if not quiet:
                console.print(
                    "  [yellow]Skipped (Local REST API not enabled or not allowed)"
                )

    if not quiet:
        if raw:
            console.print(
                "\n[yellow bold]Warning:[/yellow bold] --raw was used. Review the"
                " output for sensitive data before sharing or committing."
            )
        console.print("\n[green bold]Done!")


if __name__ == "__main__":
    cli()
