"""Fixture factories for Peblar tests.

Build fully-populated model instances with sensible defaults; individual
tests override only the fields they care about. The resulting objects are
serialized to JSON via mashumaro to simulate real charger responses.
"""

from __future__ import annotations

import orjson
from awesomeversion import AwesomeVersion

from peblar.const import (
    AccessMode,
    ChargeLimiter,
    CPState,
    LedIntensityMode,
    SolarChargingMode,
    SoundVolume,
)
from peblar.models import (
    PeblarApiToken,
    PeblarEVInterface,
    PeblarHealth,
    PeblarMeter,
    PeblarSystem,
    PeblarSystemInformation,
    PeblarUserConfiguration,
    PeblarVersions,
)


def make_system_information(**overrides: object) -> PeblarSystemInformation:
    """Return a PeblarSystemInformation with default values."""
    defaults: dict[str, object] = {
        "can_change_charging_phases": True,
        "can_charge_single_phase": True,
        "can_charge_three_phases": True,
        "customer_id": "CUST-0001",
        "customer_update_package_public_key": "dummy-pubkey",
        "ethernet_mac_address": "AA:BB:CC:DD:EE:FF",
        "firmware_version": "1.6.1",
        "hostname": "PBLR-0000001",
        "hardware_fixed_cable_rating": 32,
        "hardware_firmware_compatibility": "1.0",
        "hardware_has_bop": True,
        "hardware_has_buzzer": True,
        "hardware_has_eichrecht_laser_marking": False,
        "hardware_has_ethernet": True,
        "hardware_has_led": True,
        "hardware_has_lte": False,
        "hardware_has_meter": True,
        "hardware_has_meter_display": True,
        "hardware_has_plc": False,
        "hardware_has_rfid": True,
        "hardware_has_rs485": True,
        "hardware_has_socket": True,
        "hardware_has_tpm": True,
        "hardware_has_wlan": True,
        "hardware_max_current": 16,
        "hardware_one_or_three_phase": 3,
        "mainboard_part_number": "MB-PN-1234",
        "mainboard_serial_number": "MB-SN-5678",
        "meter_calibration_current_gain_a": 0,
        "meter_calibration_current_gain_b": 0,
        "meter_calibration_current_gain_c": 0,
        "meter_calibration_current_rms_offset_a": 0,
        "meter_calibration_current_rms_offset_b": 0,
        "meter_calibration_current_rms_offset_c": 0,
        "meter_calibration_phase_a": 0,
        "meter_calibration_phase_b": 0,
        "meter_calibration_phase_c": 0,
        "meter_calibration_voltage_gain_a": 0,
        "meter_calibration_voltage_gain_b": 0,
        "meter_calibration_voltage_gain_c": 0,
        "meter_firmware_version": "2.1.0",
        "product_model_name": "Peblar Home",
        "product_number": "PN-0001",
        "product_serial_number": "SN-0001",
        "product_vendor_name": "Peblar",
        "wlan_ap_mac_address": "11:22:33:44:55:66",
        "wlan_mac_address": "AA:11:BB:22:CC:33",
    }
    defaults.update(overrides)
    return PeblarSystemInformation(**defaults)  # ty: ignore[invalid-argument-type]


def make_user_configuration(**overrides: object) -> PeblarUserConfiguration:
    """Return a PeblarUserConfiguration with defaults matching a typical charger."""
    defaults: dict[str, object] = {
        "bop_fallback_current": 6,
        "bop_home_wizard_address": "",
        "bop_source": "Disabled",
        "bop_source_parameters": "{}",
        "connected_phases": 3,
        "current_control_bop_ct_type": "None",
        "current_control_bop_enabled": False,
        "current_control_bop_fuse_rating": 25,
        "current_control_fixed_charge_current_limit": 16,
        "ground_monitoring": True,
        "group_load_balancing_enabled": False,
        "group_load_balancing_fallback_current": 6,
        "group_load_balancing_group_id": 0,
        "group_load_balancing_interface": "eth0",
        "group_load_balancing_max_current": 16,
        "group_load_balancing_role": "Disabled",
        "buzzer_volume": SoundVolume.MEDIUM,
        "led_intensity_manual": 80,
        "led_intensity_max": 100,
        "led_intensity_min": 10,
        "led_intensity_mode": LedIntensityMode.AUTO,
        "local_rest_api_access_mode": AccessMode.READ_WRITE,
        "local_rest_api_allowed": True,
        "local_rest_api_enabled": True,
        "local_smart_charging_allowed": True,
        "modbus_server_access_mode": AccessMode.READ_ONLY,
        "modbus_server_allowed": True,
        "modbus_server_enabled": False,
        "phase_rotation": "L1-L2-L3",
        "power_limit_input_di1_inverse": False,
        "power_limit_input_di1_limit": 6,
        "power_limit_input_di2_inverse": False,
        "power_limit_input_di2_limit": 6,
        "power_limit_input_enabled": False,
        "predefined_cpo_name": "",
        "scheduled_charging_allowed": True,
        "scheduled_charging_enabled": False,
        "secc_ocpp_active": False,
        "secc_ocpp_uri": "",
        "session_manager_charge_without_authentication": True,
        "solar_charging_allowed": True,
        "solar_charging_enabled": False,
        "solar_charging_mode": SolarChargingMode.OPTIMIZED_SOLAR,
        "solar_charging_source": "Disabled",
        "solar_charging_source_parameters": {},
        "time_zone": "Europe/Amsterdam",
        "user_defined_charge_limit_current": 16,
        "user_defined_charge_limit_current_allowed": True,
        "user_defined_household_power_limit": 7400,
        "user_defined_household_power_limit_allowed": True,
        "user_defined_household_power_limit_enabled": False,
        "user_defined_household_power_limit_source": "Disabled",
        "user_keep_socket_locked": False,
        "vde_phase_imbalance_enabled": False,
        "vde_phase_imbalance_limit": 20,
        "web_if_update_helper": False,
    }
    defaults.update(overrides)
    return PeblarUserConfiguration(**defaults)  # ty: ignore[invalid-argument-type]


def user_configuration_json(**overrides: object) -> str:
    """Return a PeblarUserConfiguration serialized to wire-format JSON.

    ``BopSourceParameters`` and ``SolarChargingSourceParameters`` are stored
    as parsed JSON on the model but sent as strings by the charger, so they
    are re-serialized to strings before returning the payload.
    """
    obj = make_user_configuration(**overrides)
    raw = obj.to_dict()
    if not isinstance(raw["BopSourceParameters"], str):
        raw["BopSourceParameters"] = orjson.dumps(raw["BopSourceParameters"]).decode()
    if not isinstance(raw["SolarChargingSourceParameters"], str):
        raw["SolarChargingSourceParameters"] = orjson.dumps(
            raw["SolarChargingSourceParameters"]
        ).decode()
    return orjson.dumps(raw).decode()


def make_system(**overrides: object) -> PeblarSystem:
    """Return a PeblarSystem (Local REST API /system payload) with defaults.

    Both signal-strength fields default to real integers: the model has
    `omit_none = True`, so a None default would drop the field from the
    serialized payload and then trip MissingField on deserialization.
    """
    defaults: dict[str, object] = {
        "active_error_codes": [],
        "active_warning_codes": [],
        "cellular_signal_strength": -90,
        "firmware_version": "1.6.1+1+WL-1.0",
        "force_single_phase_allowed": True,
        "phase_count": 3,
        "product_part_number": "PN-0001",
        "product_serial_number": "SN-0001",
        "uptime": 3600,
        "wlan_signal_strength": -60,
    }
    defaults.update(overrides)
    return PeblarSystem(**defaults)


def make_meter(**overrides: object) -> PeblarMeter:
    """Return a PeblarMeter with defaults."""
    defaults: dict[str, object] = {
        "current_phase_1": 6000,
        "current_phase_2": 6000,
        "current_phase_3": 6000,
        "energy_session": 1500,
        "energy_total": 123456,
        "power_phase_1": 1380,
        "power_phase_2": 1380,
        "power_phase_3": 1380,
        "power_total": 4140,
        "voltage_phase_1": 230,
        "voltage_phase_2": 230,
        "voltage_phase_3": 230,
    }
    defaults.update(overrides)
    return PeblarMeter(**defaults)


def make_health(**overrides: object) -> PeblarHealth:
    """Return a PeblarHealth with defaults."""
    defaults: dict[str, object] = {
        "access_mode": AccessMode.READ_WRITE,
        "api_version": AwesomeVersion("1.0"),
    }
    defaults.update(overrides)
    return PeblarHealth(**defaults)


def make_ev_interface(**overrides: object) -> PeblarEVInterface:
    """Return a PeblarEVInterface with defaults."""
    defaults: dict[str, object] = {
        "charge_current_limit": 16000,
        "charge_current_limit_actual": 16000,
        "charge_current_limit_source": ChargeLimiter.CURRENT_LIMITER,
        "cp_state": CPState.CHARGING,
        "force_single_phase": False,
    }
    defaults.update(overrides)
    return PeblarEVInterface(**defaults)


def make_versions(
    firmware: str = "1.6.1+1+WL-1.0", customization: str = "Peblar-1.8"
) -> PeblarVersions:
    """Return a PeblarVersions with defaults."""
    return PeblarVersions(firmware=firmware, customization=customization)


def make_api_token(token: str = "test-api-token-abc123") -> PeblarApiToken:
    """Return a PeblarApiToken with a test token."""
    return PeblarApiToken(api_token=token)
