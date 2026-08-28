"""Asynchronous Python client for Peblar EV chargers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import orjson
from awesomeversion import AwesomeVersion
from mashumaro import field_options
from mashumaro.config import BaseConfig
from mashumaro.mixins.orjson import DataClassORJSONMixin
from mashumaro.types import SerializationStrategy

from .const import (
    AccessMode,
    AuthorizationMethod,
    ChargeLimiter,
    CPState,
    LedBrightness,
    LedIntensityMode,
    PackageType,
    SmartChargingMode,
    SolarChargingMode,
    SoundVolume,
)
from .utils import get_awesome_version


class AwesomeVersionSerializationStrategy(SerializationStrategy, use_annotations=True):
    """Serialization strategy for AwesomeVersion objects."""

    def serialize(self, value: AwesomeVersion) -> str:
        """Serialize AwesomeVersion object to string."""
        return str(value)

    def deserialize(self, value: str) -> AwesomeVersion | None:
        """Deserialize string to AwesomeVersion object."""
        version = get_awesome_version(value)
        if not version.valid:
            return None
        return version


def resolve_smart_charging_mode(
    mode: SmartChargingMode,
) -> tuple[bool, bool, SolarChargingMode | None]:
    """Translate a UI smart charging mode into the charger's own fields.

    The Peblar UI presents a single smart charging mode, while the charger
    is configured through separate scheduled and solar charging fields.
    Returns them as a (scheduled, solar, solar mode) tuple.

    Compares by value, not identity: SmartChargingMode is a StrEnum, so a
    caller handing over a plain "scheduled" has to mean the same thing as
    the member itself. Anything unrecognised raises rather than quietly
    turning both charging modes off.
    """
    if mode == SmartChargingMode.DEFAULT:
        return False, False, None

    if mode == SmartChargingMode.SCHEDULED:
        return True, False, None

    if mode == SmartChargingMode.FAST_SOLAR:
        return False, True, SolarChargingMode.MAX_SOLAR

    if mode == SmartChargingMode.SMART_SOLAR:
        return False, True, SolarChargingMode.OPTIMIZED_SOLAR

    if mode == SmartChargingMode.PURE_SOLAR:
        return False, True, SolarChargingMode.PURE_SOLAR

    msg = f"Unknown smart charging mode: {mode!r}"
    raise ValueError(msg)


def resolve_led_brightness(
    brightness: LedBrightness,
) -> tuple[LedIntensityMode, int | None]:
    """Translate a UI LED brightness level into the charger's own fields.

    Returns an (intensity mode, manual intensity) tuple; the manual
    intensity is None when the charger follows the ambient light.

    Coerces through LedBrightness, so a caller handing over a plain 22
    means the same thing as the member itself, and an intensity the UI
    has no name for raises rather than reaching the charger.
    """
    level = LedBrightness(brightness)
    if level is LedBrightness.AUTOMATIC:
        return LedIntensityMode.AUTO, None

    return LedIntensityMode.FIXED, level.value


def reject_conflicting_fields(
    ui_field: str,
    driven: dict[str, object],
) -> None:
    """Refuse a UI shorthand alongside the fields it expands into.

    The shorthand overwrites those fields, so accepting both would mean
    silently discarding half of what the caller asked for.
    """
    if conflicting := sorted(
        name for name, value in driven.items() if value is not None
    ):
        msg = (
            f"Set either {ui_field} or {', '.join(conflicting)}, not both: "
            f"{ui_field} overwrites them"
        )
        raise ValueError(msg)


class BaseModel(DataClassORJSONMixin):
    """Base model for all Peblar models."""

    # pylint: disable-next=too-few-public-methods
    class Config(BaseConfig):
        """Mashumaro configuration."""

        serialize_by_alias = True
        serialization_strategy = {  # noqa: RUF012
            AwesomeVersion: AwesomeVersionSerializationStrategy()
        }
        omit_none = True


@dataclass(kw_only=True)
class PeblarAuthStatus(BaseModel):
    """Object holding the state of the current web interface session."""

    active: bool = field(metadata=field_options(alias="Active"))
    version_hash: int = field(metadata=field_options(alias="VersionHash"))
    """Changes when the charger's software changes, invalidating the session."""


@dataclass(kw_only=True)
class PeblarConnector(BaseModel):
    """Object holding what is physically plugged into the charger."""

    plugged_in_ev: bool = field(metadata=field_options(alias="PluggedInEV"))
    """A cable is plugged into the vehicle."""

    plugged_in_evse: bool = field(metadata=field_options(alias="PluggedInEVSE"))
    """A cable is plugged into the charger."""


@dataclass(kw_only=True)
class PeblarNtpSync(BaseModel):
    """Object holding the time synchronization state of the charger."""

    time_synced: bool = field(metadata=field_options(alias="TimeSynced"))


@dataclass(kw_only=True)
class PeblarWebInterfaceMode(BaseModel):
    """Object holding the mode the charger's web interface is running in."""

    mode: str = field(metadata=field_options(alias="Mode"))


@dataclass(kw_only=True)
class PeblarApiToken(BaseModel):
    """Object holding the API token for the Peblar charger."""

    api_token: str = field(metadata=field_options(alias="ApiToken"))


@dataclass(kw_only=True)
class PeblarReboot(BaseModel):
    """Object holding the Peblar reboot payload."""

    reboot_type: str = field(
        default="HardReboot", metadata=field_options(alias="RebootType")
    )


@dataclass(kw_only=True)
class PeblarUpdate(BaseModel):
    """Object holding the update payload for the Peblar charger."""

    package_type: PackageType = field(metadata=field_options(alias="Package-Type"))


@dataclass(kw_only=True)
class PeblarLocalRestApiAccess(BaseModel):
    """Object holding the local REST API configuration of a Peblar charger."""

    access_mode: AccessMode | None = field(
        default=None, metadata=field_options(alias="LocalRestApiAccessMode")
    )
    enabled: bool | None = field(
        default=None, metadata=field_options(alias="LocalRestApiEnable")
    )


@dataclass(kw_only=True)
class PeblarModbusApiAccess(BaseModel):
    """Object holding the Modbus API configuration of a Peblar charger."""

    access_mode: AccessMode | None = field(
        default=None, metadata=field_options(alias="ModbusServerAccessMode")
    )
    enabled: bool | None = field(
        default=None, metadata=field_options(alias="ModbusServerEnable")
    )


@dataclass(kw_only=True)
class PeblarSocketLock(BaseModel):
    """Object holding the socket lock configuration of a Peblar charger."""

    user_keep_socket_locked: bool = field(
        metadata=field_options(alias="UserKeepSocketLocked")
    )


@dataclass(kw_only=True)
class PeblarBuzzerVolume(BaseModel):
    """Object holding the buzzer volume configuration of a Peblar charger."""

    buzzer_volume: SoundVolume = field(metadata=field_options(alias="HmiBuzzerVolume"))


@dataclass(kw_only=True)
class PeblarLedIntensity(BaseModel):
    """Object holding the LED intensity configuration of a Peblar charger."""

    led_intensity_mode: LedIntensityMode | None = field(
        default=None, metadata=field_options(alias="HmiLedIntensityMode")
    )
    led_intensity_manual: int | None = field(
        default=None, metadata=field_options(alias="HmiLedIntensityManual")
    )


@dataclass(kw_only=True)
class PeblarLogin(BaseModel):
    """Login request for Peblar chargers."""

    password: str = field(metadata=field_options(alias="Password"))
    persistent_session: bool = field(
        default=False, metadata=field_options(alias="PersistentSession")
    )


@dataclass(kw_only=True)
class PeblarRfidToken(BaseModel):
    """RFID token in the standalone auth list."""

    rfid_token_uid: str = field(metadata=field_options(alias="RfidTokenUid"))
    rfid_token_description: str = field(
        metadata=field_options(alias="RfidTokenDescription")
    )


@dataclass(kw_only=True)
class PeblarVehicleToken(BaseModel):
    """Vehicle in the autocharge auth list.

    Autocharge identifies a car by the EVCC ID its ISO 15118 controller
    presents, which is the vehicle equivalent of an RFID token UID.
    """

    evcc_id: str = field(metadata=field_options(alias="EvccId"))
    alias: str = field(metadata=field_options(alias="Alias"))


@dataclass(kw_only=True)
class PeblarAddVehicleToken(BaseModel):
    """Payload for adding a vehicle to the autocharge auth list."""

    evcc_id: str = field(metadata=field_options(alias="EvccId"))
    alias: str = field(metadata=field_options(alias="Alias"))
    authorize: bool = field(default=True, metadata=field_options(alias="Authorize"))


@dataclass(kw_only=True)
class PeblarChargeSessionAuthorization(BaseModel):
    """Object holding the charge session (de)authorization payload.

    The charger looks the token up in the standalone auth list, either by
    its UID or by the description it was stored under. Exactly one of the
    two is required.
    """

    method: AuthorizationMethod = field(
        default=AuthorizationMethod.RFID, metadata=field_options(alias="Method")
    )
    token: str | None = field(default=None, metadata=field_options(alias="Token"))
    name: str | None = field(default=None, metadata=field_options(alias="Name"))

    def __post_init__(self) -> None:
        """Post init hook for PeblarChargeSessionAuthorization object."""
        if (self.token is None) == (self.name is None):
            msg = "Provide exactly one of a token UID or a token name"
            raise ValueError(msg)


@dataclass(kw_only=True)
class PeblarVersions(BaseModel):
    """Object holding the version information of the Peblar charger."""

    customization: str | None = field(
        default=None, metadata=field_options(alias="Customization")
    )
    firmware: str | None = field(default=None, metadata=field_options(alias="Firmware"))

    customization_version: AwesomeVersion | None = None
    firmware_version: AwesomeVersion | None = None

    @classmethod
    def __pre_deserialize__(cls, d: dict[Any, Any]) -> dict[Any, Any]:
        """Pre deserialize hook for PeblarVersions object."""
        # Strip off everything until the first `-` for the customization
        # for AwesomeVersion to parse it correctly.
        # E.g., `Peblar-1.8`
        if customization := d.get("Customization"):
            d["customization_version"] = customization.split("-")[-1]

        # Strip off everything after the first + for the firmware
        # for AwesomeVersion to parse it correctly.
        # E.g., `1.6.1+1+WL-1.0`
        if firmware := d.get("Firmware"):
            d["firmware_version"] = firmware.split("+")[0]
        return d


@dataclass(kw_only=True)
# pylint: disable-next=too-many-instance-attributes
class PeblarSystemInformation(BaseModel):
    """Object holding information about the Peblar charger."""

    bop_calibration_current_gain_a: int | None = field(
        default=None, metadata=field_options(alias="BopCalIGainA")
    )
    bop_calibration_current_gain_b: int | None = field(
        default=None, metadata=field_options(alias="BopCalIGainB")
    )
    bop_calibration_current_gain_c: int | None = field(
        default=None, metadata=field_options(alias="BopCalIGainC")
    )
    can_change_charging_phases: bool = field(
        metadata=field_options(alias="CanChangeChargingPhases")
    )
    can_charge_single_phase: bool = field(
        metadata=field_options(alias="CanChargeSinglePhase")
    )
    can_charge_three_phases: bool = field(
        metadata=field_options(alias="CanChargeThreePhases")
    )
    customer_id: str = field(metadata=field_options(alias="CustomerId"))
    customer_update_package_public_key: str | None = field(
        default=None, metadata=field_options(alias="CustomerUpdatePackagePubKey")
    )
    ethernet_mac_address: str = field(metadata=field_options(alias="EthMacAddr"))
    firmware_version: str = field(metadata=field_options(alias="FwIdent"))
    hostname: str = field(metadata=field_options(alias="Hostname"))
    hardware_fixed_cable_rating: int | None = field(
        default=None, metadata=field_options(alias="HwFixedCableRating")
    )
    hardware_firmware_compatibility: str = field(
        metadata=field_options(alias="HwFwCompat")
    )
    hardware_has_four_pole_relay: bool | None = field(
        default=None, metadata=field_options(alias="HwHas4pRelay")
    )
    hardware_has_bop: bool = field(metadata=field_options(alias="HwHasBop"))
    hardware_has_buzzer: bool = field(metadata=field_options(alias="HwHasBuzzer"))
    hardware_has_dual_socket: bool | None = field(
        default=None, metadata=field_options(alias="HwHasDualSocket")
    )
    hardware_has_eichrecht_laser_marking: bool = field(
        metadata=field_options(alias="HwHasEichrechtLaserMarking")
    )
    hardware_has_ethernet: bool = field(metadata=field_options(alias="HwHasEthernet"))
    hardware_has_led: bool = field(metadata=field_options(alias="HwHasLed"))
    hardware_has_lte: bool = field(metadata=field_options(alias="HwHasLte"))
    hardware_has_meter: bool = field(metadata=field_options(alias="HwHasMeter"))
    hardware_has_meter_display: bool = field(
        metadata=field_options(alias="HwHasMeterDisplay")
    )
    hardware_has_plc: bool = field(metadata=field_options(alias="HwHasPlc"))
    hardware_has_rfid: bool = field(metadata=field_options(alias="HwHasRfid"))
    hardware_has_rs485: bool = field(metadata=field_options(alias="HwHasRs485"))
    hardware_has_shutter: bool | None = field(
        default=None, metadata=field_options(alias="HwHasShutter")
    )
    hardware_has_socket: bool = field(metadata=field_options(alias="HwHasSocket"))
    hardware_has_tpm: bool = field(metadata=field_options(alias="HwHasTpm"))
    hardware_has_wlan: bool = field(metadata=field_options(alias="HwHasWlan"))
    hardware_max_current: int = field(metadata=field_options(alias="HwMaxCurrent"))
    hardware_one_or_three_phase: int = field(
        metadata=field_options(alias="HwOneOrThreePhase")
    )
    hardware_uk_compliant: bool | None = field(
        default=None, metadata=field_options(alias="HwUKCompliant")
    )
    mainboard_part_number: str = field(metadata=field_options(alias="MainboardPn"))
    mainboard_serial_number: str = field(metadata=field_options(alias="MainboardSn"))
    meter_calibration_current_gain_a: int = field(
        metadata=field_options(alias="MeterCalIGainA")
    )
    meter_calibration_current_gain_b: int = field(
        metadata=field_options(alias="MeterCalIGainB")
    )
    meter_calibration_current_gain_c: int = field(
        metadata=field_options(alias="MeterCalIGainC")
    )
    meter_calibration_current_rms_offset_a: int = field(
        metadata=field_options(alias="MeterCalIRmsOffsetA")
    )
    meter_calibration_current_rms_offset_b: int = field(
        metadata=field_options(alias="MeterCalIRmsOffsetB")
    )
    meter_calibration_current_rms_offset_c: int = field(
        metadata=field_options(alias="MeterCalIRmsOffsetC")
    )
    meter_calibration_phase_a: int = field(
        metadata=field_options(alias="MeterCalPhaseA")
    )
    meter_calibration_phase_b: int = field(
        metadata=field_options(alias="MeterCalPhaseB")
    )
    meter_calibration_phase_c: int = field(
        metadata=field_options(alias="MeterCalPhaseC")
    )
    meter_calibration_voltage_gain_a: int = field(
        metadata=field_options(alias="MeterCalVGainA")
    )
    meter_calibration_voltage_gain_b: int = field(
        metadata=field_options(alias="MeterCalVGainB")
    )
    meter_calibration_voltage_gain_c: int = field(
        metadata=field_options(alias="MeterCalVGainC")
    )
    meter_firmware_version: str = field(metadata=field_options(alias="MeterFwIdent"))
    nor_flash: bool | None = field(
        default=None, metadata=field_options(alias="NorFlash")
    )
    product_model_name: str = field(metadata=field_options(alias="ProductModelName"))
    product_number: str = field(metadata=field_options(alias="ProductPn"))
    product_serial_number: str = field(metadata=field_options(alias="ProductSn"))
    product_vendor_name: str = field(metadata=field_options(alias="ProductVendorName"))
    wlan_ap_mac_address: str = field(metadata=field_options(alias="WlanApMacAddr"))
    wlan_mac_address: str = field(metadata=field_options(alias="WlanStaMacAddr"))


@dataclass(kw_only=True)
# pylint: disable-next=too-many-instance-attributes
class PeblarUserConfiguration(BaseModel):
    """Object holding user configuration of a Peblar charger."""

    bop_fallback_current: int = field(
        metadata=field_options(alias="BopFallbackCurrent")
    )
    bop_home_wizard_address: str = field(
        metadata=field_options(alias="BopHomeWizardAddress")
    )
    bop_source: str = field(metadata=field_options(alias="BopSource"))
    bop_source_parameters: dict[str, Any] = field(
        metadata=field_options(alias="BopSourceParameters")
    )
    connect_hub_visibility: bool | None = field(
        default=None, metadata=field_options(alias="ConnectHubVisibility")
    )
    connected_phases: int = field(metadata=field_options(alias="ConnectedPhases"))
    current_control_bop_ct_type: str = field(
        metadata=field_options(alias="CurrentCtrlBopCtType")
    )
    current_control_bop_enabled: bool = field(
        metadata=field_options(alias="CurrentCtrlBopEnable")
    )
    current_control_bop_fuse_rating: int = field(
        metadata=field_options(alias="CurrentCtrlBopFuseRating")
    )
    current_control_fixed_charge_current_limit: int = field(
        metadata=field_options(alias="CurrentCtrlFixedChargeCurrentLimit")
    )
    custom_customer_id: str | None = field(
        default=None, metadata=field_options(alias="CustomCustomerId")
    )
    ground_monitoring: bool = field(metadata=field_options(alias="GroundMonitoring"))
    group_load_balancing_enabled: bool = field(
        metadata=field_options(alias="GroupLoadBalancingEnable")
    )
    group_load_balancing_fallback_current: int = field(
        metadata=field_options(alias="GroupLoadBalancingFallbackCurrent")
    )
    group_load_balancing_group_id: int = field(
        metadata=field_options(alias="GroupLoadBalancingGroupId")
    )
    group_load_balancing_interface: str = field(
        metadata=field_options(alias="GroupLoadBalancingInterface")
    )
    group_load_balancing_max_current: int = field(
        metadata=field_options(alias="GroupLoadBalancingMaxCurrent")
    )
    group_load_balancing_role: str = field(
        metadata=field_options(alias="GroupLoadBalancingRole")
    )
    buzzer_volume: SoundVolume = field(metadata=field_options(alias="HmiBuzzerVolume"))
    led_intensity_manual: int = field(
        metadata=field_options(alias="HmiLedIntensityManual")
    )
    led_intensity_max: int = field(metadata=field_options(alias="HmiLedIntensityMax"))
    led_intensity_min: int = field(metadata=field_options(alias="HmiLedIntensityMin"))
    led_intensity_mode: LedIntensityMode = field(
        metadata=field_options(alias="HmiLedIntensityMode")
    )
    iso15118_communication_enabled: bool | None = field(
        default=None, metadata=field_options(alias="Iso15118CommunicationEnable")
    )
    local_rest_api_access_mode: AccessMode = field(
        metadata=field_options(alias="LocalRestApiAccessMode")
    )
    local_rest_api_allowed: bool = field(
        metadata=field_options(alias="LocalRestApiAllowed")
    )
    local_rest_api_enabled: bool = field(
        metadata=field_options(alias="LocalRestApiEnable")
    )
    local_smart_charging_allowed: bool = field(
        metadata=field_options(alias="LocalSmartChargingAllowed")
    )
    modbus_server_access_mode: AccessMode = field(
        metadata=field_options(alias="ModbusServerAccessMode")
    )
    modbus_server_allowed: bool = field(
        metadata=field_options(alias="ModbusServerAllowed")
    )
    modbus_server_enabled: bool = field(
        metadata=field_options(alias="ModbusServerEnable")
    )
    phase_rotation: str = field(metadata=field_options(alias="PhaseRotation"))
    power_limit_input_di1_inverse: bool = field(
        metadata=field_options(alias="PowerLimitInputDi1Inverse")
    )
    power_limit_input_di1_limit: int = field(
        metadata=field_options(alias="PowerLimitInputDi1Limit")
    )
    power_limit_input_di2_inverse: bool = field(
        metadata=field_options(alias="PowerLimitInputDi2Inverse")
    )
    power_limit_input_di2_limit: int = field(
        metadata=field_options(alias="PowerLimitInputDi2Limit")
    )
    power_limit_input_enabled: bool = field(
        metadata=field_options(alias="PowerLimitInputEnable")
    )
    predefined_cpo_name: str = field(metadata=field_options(alias="PredefinedCpoName"))
    sbo_allowed: bool | None = field(
        default=None, metadata=field_options(alias="SboAllowed")
    )
    sbo_enabled: str | None = field(
        default=None, metadata=field_options(alias="SboEnabled")
    )
    scheduled_charging_allowed: bool = field(
        metadata=field_options(alias="ScheduledChargingAllowed")
    )
    scheduled_charging_enabled: bool = field(
        metadata=field_options(alias="ScheduledChargingEnable")
    )
    secc_ocpp_active: bool = field(metadata=field_options(alias="SeccOcppActive"))
    secc_ocpp_uri: str = field(metadata=field_options(alias="SeccOcppUri"))
    session_download_allowed: bool | None = field(
        default=None, metadata=field_options(alias="SessionDownloadAllowed")
    )
    session_manager_charge_without_authentication: bool = field(
        metadata=field_options(alias="SessionManagerChargeWithoutAuth")
    )
    solar_charging_allowed: bool = field(
        metadata=field_options(alias="SolarChargingAllowed")
    )
    solar_charging_enabled: bool = field(
        metadata=field_options(alias="SolarChargingEnable")
    )
    solar_charging_mode: SolarChargingMode = field(
        metadata=field_options(alias="SolarChargingMode")
    )
    solar_charging_source: str = field(
        metadata=field_options(alias="SolarChargingSource")
    )
    solar_charging_source_parameters: dict[str, Any] = field(
        metadata=field_options(alias="SolarChargingSourceParameters")
    )
    time_zone: str = field(metadata=field_options(alias="TimeZone"))
    user_defined_charge_limit_current: int = field(
        metadata=field_options(alias="UserDefinedChargeLimitCurrent")
    )
    user_defined_charge_limit_current_allowed: bool = field(
        metadata=field_options(alias="UserDefinedChargeLimitCurrentAllowed")
    )
    user_defined_household_power_limit: int = field(
        metadata=field_options(alias="UserDefinedHouseholdPowerLimit")
    )
    user_defined_household_power_limit_allowed: bool = field(
        metadata=field_options(alias="UserDefinedHouseholdPowerLimitAllowed")
    )
    user_defined_household_power_limit_enabled: bool = field(
        metadata=field_options(alias="UserDefinedHouseholdPowerLimitEnable")
    )
    user_defined_household_power_limit_source: str = field(
        metadata=field_options(alias="UserDefinedHouseholdPowerLimitSource")
    )
    user_defined_household_power_limit_source_parameters: dict[str, Any] = field(
        default_factory=dict,
        metadata=field_options(alias="UserDefinedHouseholdPowerLimitSourceParameters"),
    )
    user_keep_socket_locked: bool = field(
        metadata=field_options(alias="UserKeepSocketLocked")
    )
    vde_phase_imbalance_enabled: bool = field(
        metadata=field_options(alias="VDEPhaseImbalanceEnable")
    )
    vde_phase_imbalance_limit: int = field(
        metadata=field_options(alias="VDEPhaseImbalanceLimit")
    )
    web_if_update_helper: bool = field(
        metadata=field_options(alias="WebIfUpdateHelper")
    )

    # Replicated field from the Peblar UI
    smart_charging: SmartChargingMode | None = None
    led_brightness: LedBrightness | None = None

    @classmethod
    def __pre_deserialize__(cls, d: dict[Any, Any]) -> dict[Any, Any]:
        """Pre deserialize hook for PeblarUserConfiguration object."""
        for key in (
            "BopSourceParameters",
            "SolarChargingSourceParameters",
            "UserDefinedHouseholdPowerLimitSourceParameters",
        ):
            # The charger sends these JSON encoded, but tolerate a blob that
            # is already a mapping so feeding back an earlier result does
            # not blow up on a second decode.
            blob = d.get(key)
            if isinstance(blob, str) or blob is None:
                blob = orjson.loads(blob or "{}")
            d[key] = blob
        return d

    @classmethod
    def __post_deserialize__(
        cls, obj: PeblarUserConfiguration
    ) -> PeblarUserConfiguration:
        """Post deserialize hook for PeblarUserConfiguration object."""
        if not obj.scheduled_charging_enabled and not obj.solar_charging_enabled:
            obj.smart_charging = SmartChargingMode.DEFAULT
        elif obj.scheduled_charging_enabled and not obj.solar_charging_enabled:
            obj.smart_charging = SmartChargingMode.SCHEDULED
        elif not obj.scheduled_charging_enabled and obj.solar_charging_enabled:
            if obj.solar_charging_mode == SolarChargingMode.MAX_SOLAR:
                obj.smart_charging = SmartChargingMode.FAST_SOLAR
            elif obj.solar_charging_mode == SolarChargingMode.OPTIMIZED_SOLAR:
                obj.smart_charging = SmartChargingMode.SMART_SOLAR
            elif obj.solar_charging_mode == SolarChargingMode.PURE_SOLAR:
                obj.smart_charging = SmartChargingMode.PURE_SOLAR

        if obj.led_intensity_mode == LedIntensityMode.AUTO:
            obj.led_brightness = LedBrightness.AUTOMATIC
        else:
            try:
                obj.led_brightness = LedBrightness(obj.led_intensity_manual)
            except ValueError:
                obj.led_brightness = None

        return obj


@dataclass(kw_only=True)
# pylint: disable-next=too-many-instance-attributes
class PeblarSetUserConfiguration(BaseModel):
    """Object to set user configuration of a Peblar charger.

    Mirrors the writable half of PeblarUserConfiguration. Every field is
    optional and only the ones that are set end up in the request, so a
    single call can change one setting or all of them at once.
    """

    buzzer_volume: SoundVolume | None = field(
        default=None, metadata=field_options(alias="HmiBuzzerVolume")
    )
    led_intensity_manual: int | None = field(
        default=None, metadata=field_options(alias="HmiLedIntensityManual")
    )
    led_intensity_mode: LedIntensityMode | None = field(
        default=None, metadata=field_options(alias="HmiLedIntensityMode")
    )
    local_rest_api_access_mode: AccessMode | None = field(
        default=None, metadata=field_options(alias="LocalRestApiAccessMode")
    )
    local_rest_api_enabled: bool | None = field(
        default=None, metadata=field_options(alias="LocalRestApiEnable")
    )
    modbus_server_access_mode: AccessMode | None = field(
        default=None, metadata=field_options(alias="ModbusServerAccessMode")
    )
    modbus_server_enabled: bool | None = field(
        default=None, metadata=field_options(alias="ModbusServerEnable")
    )
    scheduled_charging_enabled: bool | None = field(
        default=None, metadata=field_options(alias="ScheduledChargingEnable")
    )
    solar_charging_enabled: bool | None = field(
        default=None, metadata=field_options(alias="SolarChargingEnable")
    )
    solar_charging_mode: SolarChargingMode | None = field(
        default=None, metadata=field_options(alias="SolarChargingMode")
    )
    user_defined_charge_limit_current: int | None = field(
        default=None, metadata=field_options(alias="UserDefinedChargeLimitCurrent")
    )
    user_defined_household_power_limit: int | None = field(
        default=None,
        metadata=field_options(alias="UserDefinedHouseholdPowerLimit"),
    )
    user_defined_household_power_limit_enabled: bool | None = field(
        default=None,
        metadata=field_options(alias="UserDefinedHouseholdPowerLimitEnable"),
    )
    user_keep_socket_locked: bool | None = field(
        default=None, metadata=field_options(alias="UserKeepSocketLocked")
    )

    # Replicated fields from the Peblar UI
    led_brightness: LedBrightness | None = field(
        default=None, metadata=field_options(serialize="omit")
    )
    smart_charging: SmartChargingMode | None = field(
        default=None, metadata=field_options(serialize="omit")
    )

    def __post_init__(self) -> None:
        """Post init hook for PeblarSetUserConfiguration object."""
        if self.smart_charging is not None:
            reject_conflicting_fields(
                "smart_charging",
                {
                    "scheduled_charging_enabled": self.scheduled_charging_enabled,
                    "solar_charging_enabled": self.solar_charging_enabled,
                    "solar_charging_mode": self.solar_charging_mode,
                },
            )
            (
                self.scheduled_charging_enabled,
                self.solar_charging_enabled,
                solar_charging_mode,
            ) = resolve_smart_charging_mode(self.smart_charging)

            if solar_charging_mode is not None:
                self.solar_charging_mode = solar_charging_mode

        if self.led_brightness is not None:
            reject_conflicting_fields(
                "led_brightness",
                {
                    "led_intensity_mode": self.led_intensity_mode,
                    "led_intensity_manual": self.led_intensity_manual,
                },
            )
            self.led_intensity_mode, self.led_intensity_manual = resolve_led_brightness(
                self.led_brightness
            )


@dataclass(kw_only=True)
class PeblarSmartCharging(BaseModel):
    """Object holding the configuration of the Peblar charger."""

    solar_charging_enable: bool | None = field(
        default=None, metadata=field_options(alias="SolarChargingEnable")
    )
    solar_charging_mode: SolarChargingMode | None = field(
        default=None, metadata=field_options(alias="SolarChargingMode")
    )
    scheduled_charging_enable: bool | None = field(
        default=None, metadata=field_options(alias="ScheduledChargingEnable")
    )

    # Replicated field from the Peblar UI
    smart_charging: SmartChargingMode | None = field(
        default=None, metadata=field_options(serialize="omit")
    )

    def __post_init__(self) -> None:
        """Post init hook for PeblarSmartCharging object."""
        if self.smart_charging is None:
            return

        reject_conflicting_fields(
            "smart_charging",
            {
                "scheduled_charging_enable": self.scheduled_charging_enable,
                "solar_charging_enable": self.solar_charging_enable,
                "solar_charging_mode": self.solar_charging_mode,
            },
        )

        (
            self.scheduled_charging_enable,
            self.solar_charging_enable,
            solar_charging_mode,
        ) = resolve_smart_charging_mode(self.smart_charging)

        if solar_charging_mode is not None:
            self.solar_charging_mode = solar_charging_mode


@dataclass(kw_only=True)
class PeblarHealth(BaseModel):
    """Object holding the health information of the Peblar charger."""

    access_mode: AccessMode = field(metadata=field_options(alias="AccessMode"))
    api_version: AwesomeVersion = field(metadata=field_options(alias="ApiVersion"))


@dataclass(kw_only=True)
# pylint: disable-next=too-many-instance-attributes
class PeblarSystem(BaseModel):
    """Object holding the system information of the Peblar charger."""

    active_error_codes: list[str] = field(
        metadata=field_options(alias="ActiveErrorCodes")
    )
    active_warning_codes: list[str] = field(
        metadata=field_options(alias="ActiveWarningCodes")
    )
    cellular_signal_strength: int | None = field(
        default=None, metadata=field_options(alias="CellularSignalStrength")
    )
    firmware_version: str = field(metadata=field_options(alias="FirmwareVersion"))
    force_single_phase_allowed: bool = field(
        metadata=field_options(alias="Force1PhaseAllowed")
    )
    phase_count: int = field(metadata=field_options(alias="PhaseCount"))
    product_part_number: str = field(metadata=field_options(alias="ProductPn"))
    product_serial_number: str = field(metadata=field_options(alias="ProductSn"))
    uptime: int = field(metadata=field_options(alias="Uptime"))
    wlan_signal_strength: int | None = field(
        default=None, metadata=field_options(alias="WlanSignalStrength")
    )


@dataclass(kw_only=True)
class PeblarMeterHistoryMetaData(BaseModel):
    """Meter history metadata."""

    meter_hash: str = field(metadata=field_options(alias="MeterHash"))
    meter_version: str = field(metadata=field_options(alias="MeterVersion"))
    mid_certified: bool = field(metadata=field_options(alias="MidCertified"))
    product_pn: str = field(metadata=field_options(alias="ProductPn"))
    product_sn: str = field(metadata=field_options(alias="ProductSn"))
    time_zone: str = field(metadata=field_options(alias="TimeZone"))


@dataclass(kw_only=True)
class PeblarMeterHistorySession(BaseModel):
    """Single meter history session entry."""

    auth_token: str | None = field(
        default=None,
        metadata=field_options(alias="AuthToken"),
    )
    checksum: int = field(metadata=field_options(alias="Checksum"))
    session_number: int = field(metadata=field_options(alias="SessionNumber"))
    session_start_energy_mwh: int = field(
        metadata=field_options(alias="SessionStartEnergymWh")
    )
    session_start_time: int = field(metadata=field_options(alias="SessionStartTime"))
    session_end_energy_mwh: int | None = field(
        default=None,
        metadata=field_options(alias="SessionEndEnergymWh"),
    )
    session_end_time: int | None = field(
        default=None,
        metadata=field_options(alias="SessionEndTime"),
    )


@dataclass(kw_only=True)
class PeblarMeterHistory(BaseModel):
    """Meter history response."""

    corrupted: bool = field(metadata=field_options(alias="Corrupted"))
    corrupted_session: list[bool] = field(
        metadata=field_options(alias="CorruptedSession")
    )
    meta_data: PeblarMeterHistoryMetaData | None = field(
        default=None, metadata=field_options(alias="MetaData")
    )
    session: list[PeblarMeterHistorySession] = field(
        metadata=field_options(alias="Session")
    )


@dataclass(kw_only=True)
class PeblarSessionGraphPoint(BaseModel):
    """Single measurement in the charging session graph.

    Note the charger uses camelCase on this endpoint, unlike the rest of
    the web API.
    """

    average_power: list[int] = field(metadata=field_options(alias="averagePower"))
    """Average power per phase, in Watts."""

    timestamp: datetime = field(metadata=field_options(alias="timestamp"))

    @property
    def average_power_total(self) -> int:
        """Return the average power over all phases, in Watts."""
        return sum(self.average_power)


@dataclass(kw_only=True)
class PeblarSessionGraph(BaseModel):
    """Object holding the power graph of the current or last charging session.

    The charger returns the measurements newest first.
    """

    data: list[PeblarSessionGraphPoint] = field(metadata=field_options(alias="data"))


@dataclass(kw_only=True)
class PeblarEnergyHistoryMonth(BaseModel):
    """Energy delivered per day within a single month, in Wh."""

    energy: list[int] = field(metadata=field_options(alias="Energy"))
    """One entry per day of the month."""

    month: int = field(metadata=field_options(alias="Month"))
    year: int = field(metadata=field_options(alias="Year"))


@dataclass(kw_only=True)
class PeblarEnergyHistoryYear(BaseModel):
    """Energy delivered per month within a single year, in Wh."""

    energy: list[int] = field(metadata=field_options(alias="Energy"))
    """One entry per month of the year."""

    year: int = field(metadata=field_options(alias="Year"))


@dataclass(kw_only=True)
class PeblarEnergyHistory(BaseModel):
    """Object holding the long term energy history of the charger."""

    months: list[PeblarEnergyHistoryMonth] = field(
        metadata=field_options(alias="HistoryMonth")
    )
    years: list[PeblarEnergyHistoryYear] = field(
        metadata=field_options(alias="HistoryYear")
    )


@dataclass(kw_only=True)
class PeblarScheduleSlot(BaseModel):
    """Single slot in the local charging schedule."""

    current_limit: int = field(metadata=field_options(alias="CurrentLimit"))
    """Charge current limit for this slot, in Amperes. Zero means no charging."""

    start_time: int = field(metadata=field_options(alias="StartTime"))
    """Start of the slot, in minutes since midnight."""


@dataclass(kw_only=True)
class PeblarScheduledCharging(BaseModel):
    """Object holding the local charging schedule, one list per weekday."""

    monday: list[PeblarScheduleSlot] = field(metadata=field_options(alias="Monday"))
    tuesday: list[PeblarScheduleSlot] = field(metadata=field_options(alias="Tuesday"))
    wednesday: list[PeblarScheduleSlot] = field(
        metadata=field_options(alias="Wednesday")
    )
    thursday: list[PeblarScheduleSlot] = field(metadata=field_options(alias="Thursday"))
    friday: list[PeblarScheduleSlot] = field(metadata=field_options(alias="Friday"))
    saturday: list[PeblarScheduleSlot] = field(metadata=field_options(alias="Saturday"))
    sunday: list[PeblarScheduleSlot] = field(metadata=field_options(alias="Sunday"))

    @property
    def by_weekday(self) -> dict[int, list[PeblarScheduleSlot]]:
        """Return the schedule keyed the way datetime.weekday() numbers days."""
        return {
            0: self.monday,
            1: self.tuesday,
            2: self.wednesday,
            3: self.thursday,
            4: self.friday,
            5: self.saturday,
            6: self.sunday,
        }


@dataclass(kw_only=True)
class PeblarEVInterface(BaseModel):
    """Object holding the EV interface information of the Peblar charger."""

    charge_current_limit: int = field(
        metadata=field_options(alias="ChargeCurrentLimit")
    )
    charge_current_limit_actual: int = field(
        metadata=field_options(alias="ChargeCurrentLimitActual")
    )
    charge_current_limit_source: ChargeLimiter = field(
        metadata=field_options(alias="ChargeCurrentLimitSource")
    )
    cp_state: CPState = field(metadata=field_options(alias="CpState"))
    force_single_phase: bool = field(metadata=field_options(alias="Force1Phase"))
    lock_state: bool | None = field(
        default=None, metadata=field_options(alias="LockState")
    )


@dataclass(kw_only=True)
class PeblarEVInterfaceChange(BaseModel):
    """Object holding the EV interface change payload."""

    charge_current_limit: int | None = field(
        default=None, metadata=field_options(alias="ChargeCurrentLimit")
    )
    force_single_phase: bool | None = field(
        default=None, metadata=field_options(alias="Force1Phase")
    )


@dataclass(kw_only=True)
class PeblarEVInterfaceReplace(BaseModel):
    """Object holding the complete EV interface configuration payload.

    Unlike a change payload, the charger rejects a replacement that leaves
    any writable field out, so both fields are required here.
    """

    charge_current_limit: int = field(
        metadata=field_options(alias="ChargeCurrentLimit")
    )
    force_single_phase: bool = field(metadata=field_options(alias="Force1Phase"))


@dataclass(kw_only=True)
# pylint: disable-next=too-many-instance-attributes
class PeblarMeter(BaseModel):
    """Object holding the meter information of the Peblar charger.

    Single phase chargers leave the phase 2 and 3 fields out of the
    response entirely rather than reporting zeros, so those are optional.
    The voltages are optional on top of that, phase 1 included, since the
    charger reports nothing for a phase it cannot currently measure.

    A field reading None means the charger did not report it, which is
    not the same as it reporting 0.
    """

    current_phase_1: int = field(metadata=field_options(alias="CurrentPhase1"))
    current_phase_2: int | None = field(
        default=None, metadata=field_options(alias="CurrentPhase2")
    )
    current_phase_3: int | None = field(
        default=None, metadata=field_options(alias="CurrentPhase3")
    )
    energy_session: int = field(metadata=field_options(alias="EnergySession"))
    energy_total: int = field(metadata=field_options(alias="EnergyTotal"))
    power_phase_1: int = field(metadata=field_options(alias="PowerPhase1"))
    power_phase_2: int | None = field(
        default=None, metadata=field_options(alias="PowerPhase2")
    )
    power_phase_3: int | None = field(
        default=None, metadata=field_options(alias="PowerPhase3")
    )
    power_total: int = field(metadata=field_options(alias="PowerTotal"))
    voltage_phase_1: int | None = field(
        default=None, metadata=field_options(alias="VoltagePhase1")
    )
    voltage_phase_2: int | None = field(
        default=None, metadata=field_options(alias="VoltagePhase2")
    )
    voltage_phase_3: int | None = field(
        default=None, metadata=field_options(alias="VoltagePhase3")
    )

    @property
    def current_total(self) -> int:
        """Return the total current of the Peblar charger.

        Phases the charger does not have are left out rather than counted
        as zero, so a single phase charger totals just its one phase.
        """
        return sum(
            current
            for current in (
                self.current_phase_1,
                self.current_phase_2,
                self.current_phase_3,
            )
            if current is not None
        )
