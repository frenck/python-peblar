"""Asynchronous Python client for Peblar EV chargers."""

import asyncio
import sys
from typing import Annotated

import typer
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from zeroconf import ServiceStateChange, Zeroconf
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

from peblar.const import AccessMode, CPState, PackageType, SmartChargingMode
from peblar.exceptions import (
    PeblarAuthenticationError,
    PeblarConnectionError,
    PeblarUnsupportedFirmwareVersionError,
)
from peblar.peblar import Peblar

from .async_typer import AsyncTyper

cli = AsyncTyper(help="Peblar CLI", no_args_is_help=True, add_completion=False)
console = Console()


def convert_to_string(value: object) -> str:
    """Convert a value to a string."""
    if isinstance(value, bool):
        return "✅" if value else "❌"
    if isinstance(value, dict):
        return "".join(f"{key}: {value}" for key, value in value.items())
    return str(value)


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
) -> None:
    """Get the software version information the Peblar charger."""
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
) -> None:
    """Flash the LEDs on the Peblar charger to identify it."""
    with console.status("[cyan]Identifying...", spinner="toggle12"):
        async with Peblar(host=host) as peblar:
            await peblar.login(password=password)
            await peblar.identify()
    console.print("✅[green]Success!")


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
) -> None:
    """Reboot the Peblar charger."""
    with console.status("[cyan]Rebooting...", spinner="toggle12"):
        async with Peblar(host=host) as peblar:
            await peblar.login(password=password)
            await peblar.reboot()
    console.print("✅[green]Success!")


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
) -> None:
    """Update the Peblar charger."""
    if not firmware and not customization:
        msg = "At least one of --firmware or --customization must be used."
        raise typer.BadParameter(msg)
    if firmware and customization:
        msg = "--firmware cannot be used with --customization."
        raise typer.BadParameter(msg)

    with console.status("[cyan]Updating...", spinner="toggle12"):
        async with Peblar(host=host) as peblar:
            await peblar.login(password=password)
            if firmware:
                await peblar.update(package_type=PackageType.FIRMWARE)
            if customization:
                await peblar.update(package_type=PackageType.CUSTOMIZATION)

    console.print("✅[green]Success!")


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
            help="Set access mode to read-only",
        ),
    ] = False,
    generate_new_token: Annotated[
        bool,
        typer.Option(
            help="Generate a new API token",
        ),
    ] = False,
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
            with console.status("[cyan]Adjusting...", spinner="toggle12"):
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
            console.print("✅[green]Success!")

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
            help="Set access mode to read-only",
        ),
    ] = False,
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
            with console.status("[cyan]Adjusting...", spinner="toggle12"):
                if enable:
                    await peblar.modbus_api(enable=True)
                if disable:
                    await peblar.modbus_api(enable=False)
                if read:
                    await peblar.modbus_api(access_mode=AccessMode.READ_ONLY)
                if write:
                    await peblar.modbus_api(access_mode=AccessMode.READ_WRITE)
            console.print("✅[green]Success!")
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
        f"{info.hardware_fixed_cable_rating}A",
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
) -> None:
    """List information about the user configuration."""
    async with Peblar(host=host) as peblar:
        await peblar.login(password=password)
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

    with console.status("[cyan]Adjusting...", spinner="toggle12"):
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

    console.print("✅[green]Success!")


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
) -> None:
    """Get the EV interface status of the Peblar charger."""
    async with Peblar(host=host) as peblar:
        await peblar.login(password=password)
        async with await peblar.rest_api() as api:
            if charge_limit is not None or force_single_phase is not None:
                with console.status("[cyan]Adjusting...", spinner="toggle12"):
                    await api.ev_interface(
                        charge_current_limit=charge_limit * 1000
                        if charge_limit
                        else None,
                        force_single_phase=force_single_phase,
                    )
                console.print("✅[green]Success")

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
async def scan() -> None:
    """Scan for Peblar chargers on the network."""
    zeroconf = AsyncZeroconf()
    background_tasks = set()

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
        await info.async_request(zeroconf, 3000)
        if info is None:
            return

        if info.properties is None or not str(info.server).startswith("PBLR-"):
            return

        console.print(f"[cyan bold]Found service {info.server}: is a Peblar charger 🎉")

        table.add_row(
            f"{str(info.server).rstrip('.')}\n"
            + ", ".join(info.parsed_scoped_addresses()),
            info.properties[b"sn"].decode(),  # type: ignore[union-attr]
            info.properties[b"version"].decode(),  # type: ignore[union-attr]
        )

    console.print("[green]Scanning for Peblar chargers...")
    console.print("[red]Press Ctrl-C to exit\n")

    with Live(table, console=console, refresh_per_second=4):
        browser = AsyncServiceBrowser(
            zeroconf.zeroconf,
            "_http._tcp.local.",
            handlers=[async_on_service_state_change],
        )

        try:
            while True:  # noqa: ASYNC110
                await asyncio.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            console.print("\n[green]Control-C pressed, stopping scan")
            await browser.async_cancel()
            await zeroconf.async_close()


if __name__ == "__main__":
    cli()
