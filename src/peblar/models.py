"""Asynchronous Python client for Peblar EV chargers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import orjson
from awesomeversion import AwesomeVersion
from mashumaro import field_options
from mashumaro.config import BaseConfig
from mashumaro.mixins.orjson import DataClassORJSONMixin
from mashumaro.types import SerializationStrategy

from .const import AccessMode, LedIntensityMode, SolarChargingMode, SoundVolume
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
class PeblarApiToken(BaseModel):
    """Object holding the API token for the Peblar charger."""

    api_token: str = field(metadata=field_options(alias="ApiToken"))


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
class PeblarLogin(BaseModel):
    """Login request for Peblar chargers."""

    password: str = field(metadata=field_options(alias="Password"))
    persistent_session: bool = field(
        default=False, metadata=field_options(alias="PersistentSession")
    )


@dataclass(kw_only=True)
class PeblarVersions(BaseModel):
    """Object holding the version information of the Peblar charger."""

    customization: str = field(metadata=field_options(alias="Customization"))
    firmware: str = field(metadata=field_options(alias="Firmware"))

    customization_version: AwesomeVersion
    firmware_version: AwesomeVersion

    @classmethod
    def __pre_deserialize__(cls, d: dict[Any, Any]) -> dict[Any, Any]:
        """Pre deserialize hook for PeblarVersions object."""
        # Strip off everything until the first `-` for the customization
        # for AwesomeVersion to parse it correctly.
        # E.g., `Peblar-1.8`
        d["customization_version"] = d.get("Customization", "").split("-")[-1]

        # Strip off everything after the first + for the firmware
        # for AwesomeVersion to parse it correctly.
        # E.g., `1.6.1+1+WL-1.0`
        d["firmware_version"] = d.get("Firmware", "").split("+")[0]
        return d


@dataclass(kw_only=True)
# pylint: disable-next=too-many-instance-attributes
class PeblarSystemInformation(BaseModel):
    """Object holding information about the Peblar charger."""

    bop_calibration_current_gain_a: int = field(
        metadata=field_options(alias="BopCalIGainA")
    )
    bop_calibration_current_gain_b: int = field(
        metadata=field_options(alias="BopCalIGainB")
    )
    bop_calibration_current_gain_c: int = field(
        metadata=field_options(alias="BopCalIGainC")
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
    customer_update_package_public_key: str = field(
        metadata=field_options(alias="CustomerUpdatePackagePubKey")
    )
    ethernet_mac_address: str = field(metadata=field_options(alias="EthMacAddr"))
    firmware_version: str = field(metadata=field_options(alias="FwIdent"))
    hostname: str = field(metadata=field_options(alias="Hostname"))
    hardware_fixed_cable_rating: int = field(
        metadata=field_options(alias="HwFixedCableRating")
    )
    hardware_firmware_compatibility: str = field(
        metadata=field_options(alias="HwFwCompat")
    )
    hardware_has_4p_relay: bool = field(metadata=field_options(alias="HwHas4pRelay"))
    hardware_has_bop: bool = field(metadata=field_options(alias="HwHasBop"))
    hardware_has_buzzer: bool = field(metadata=field_options(alias="HwHasBuzzer"))
    hardware_has_dual_socket: bool = field(
        metadata=field_options(alias="HwHasDualSocket")
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
    hardware_has_shutter: bool = field(metadata=field_options(alias="HwHasShutter"))
    hardware_has_socket: bool = field(metadata=field_options(alias="HwHasSocket"))
    hardware_has_tpm: bool = field(metadata=field_options(alias="HwHasTpm"))
    hardware_has_wlan: bool = field(metadata=field_options(alias="HwHasWlan"))
    hardware_max_current: int = field(metadata=field_options(alias="HwMaxCurrent"))
    hardware_one_or_three_phase: int = field(
        metadata=field_options(alias="HwOneOrThreePhase")
    )
    hardware_uk_compliant: bool = field(metadata=field_options(alias="HwUKCompliant"))
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
    nor_flash: str = field(metadata=field_options(alias="NorFlash"))
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
    bop_source_parameters: str = field(
        metadata=field_options(alias="BopSourceParameters")
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
    scheduled_charging_allowed: bool = field(
        metadata=field_options(alias="ScheduledChargingAllowed")
    )
    scheduled_charging_enabled: bool = field(
        metadata=field_options(alias="ScheduledChargingEnable")
    )
    secc_ocpp_active: bool = field(metadata=field_options(alias="SeccOcppActive"))
    secc_ocpp_uri: str = field(metadata=field_options(alias="SeccOcppUri"))
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

    @classmethod
    def __pre_deserialize__(cls, d: dict[Any, Any]) -> dict[Any, Any]:
        """Pre deserialize hook for PeblarUserConfiguration object."""
        d["SolarChargingSourceParameters"] = orjson.loads(
            d.get("SolarChargingSourceParameters", "{}")
        )
        d["BopSourceParameters"] = orjson.loads(d.get("BopSourceParameters", "{}"))
        return d
