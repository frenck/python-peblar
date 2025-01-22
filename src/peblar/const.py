"""Asynchronous Python client for Peblar EV chargers."""

from enum import IntEnum, StrEnum


class AccessMode(StrEnum):
    """Peblar access mode."""

    READ_WRITE = "ReadWrite"
    """Read and write access."""

    READ_ONLY = "ReadOnly"
    """Read only access."""


class SolarChargingMode(StrEnum):
    """Peblar solar charging mode."""

    MAX_SOLAR = "MaxSolar"
    """Fast charge with a mix of grid and solar power."""

    OPTIMIZED_SOLAR = "OptimizedSolar"
    """Charge with a smart mix of grid and solar power."""

    PURE_SOLAR = "PureSolar"
    """Charge only with solar power."""


class SoundVolume(IntEnum):
    """Peblar sound volume."""

    OFF = 0
    """Sound off."""

    LOW = 1
    """Low sound volume."""

    LOW_MEDIUM = 2
    """Low medium sound volume. NOTE: Not present in the UI."""

    MEDIUM = 3
    """Medium sound volume."""

    HIGH = 4
    """High sound volume."""


class LedIntensityMode(StrEnum):
    """Peblar LED intensity mode."""

    AUTO = "Auto"
    """Automatic LED intensity."""

    FIXED = "Fixed"
    """Fixed LED intensity."""


class SmartChargingMode(StrEnum):
    """Peblar smart charging mode."""

    DEFAULT = "default"
    """Not limited by any strategy."""

    FAST_SOLAR = "fast_solar"
    """Fast charge with a mix of grid and solar power."""

    SMART_SOLAR = "smart_solar"
    """Charge with a smart mix of grid and solar power."""

    PURE_SOLAR = "pure_solar"
    """Charge only with solar power."""

    SCHEDULED = "scheduled"
    "Charge only within the defined schedule."


class ChargeLimiter(StrEnum):
    """Peblar charge limiter."""

    CHARGING_CABLE = "Charging cable"
    """Charging limited by the maximum rated current of the attached cable."""

    CURRENT_LIMITER = "Current limiter"
    """Charging limited by the user-defined maximum current."""

    DYNAMIC_LOAD_BALANCING = "Dynamic load balancing"
    """Charging limited by the maximum current due to dynamic load balancing."""

    EXTERNAL_POWER_LIMIT = "External power limit"
    """Charging limited by the maximum current due to external power limit."""

    GROUP_LOAD_BALANCING = "Group load balancing"
    """Charging limited by the maximum current due to group load balancing."""

    HARDWARE_LIMITATION = "Hardware limitation"
    """Charging limited by the maximum current due to hardware limitation."""

    HIGH_TEMPERATURE = "High temperature"
    """Charging is limited due to high temperature in charger."""

    HOUSEHOLD_POWER_LIMIT = "Household power limit"
    """Charging limited by total power consumption of the household."""

    INSTALLATION_LIMIT = "Installation limit"
    """Charging limited by the maximum installation current configured."""

    LOCAL_MODBUS_API = "Local Modbus API"
    """Charging limited by the maximum current by local Modbus API."""

    LOCAL_REST_API = "Local REST API"
    """Charging limited by the maximum current by local REST API."""

    LOCAL_SCHEDULED_CHARGING = "Local scheduled charging"
    """Charging limited by the local schedule."""

    OCPP_SMART_CHARGING = "OCPP smart charging"
    """Charging limited by the maximum current by OCPP profile."""

    OVERCURRENT_PROTECTION = "Overcurrent protection"
    """Charging limited by the maximum current due to overcurrent protection."""

    PHASE_IMBALANCE = "Phase imbalance"
    """Charging limited by the maximum current due to phase imbalance."""

    POWER_FACTOR = "Power factor"
    """Charging limited by the maximum current due to power factor."""

    SOLAR_CHARGING = "Solar charging"
    """Charging limited by the maximum current due to solar charging."""


class CPState(StrEnum):
    """Peblar CP state."""

    NO_EV_CONNECTED = "State A"
    """No EV connected."""

    CHARGING_SUSPENDED = "State B"
    """EV connected, byt charging suspended by EV or charger."""

    CHARGING = "State C"
    """EV connected and charging."""

    CHARGING_VENTILATION = "State D"
    """EV connected and charging, but ventilation requested (unused)."""

    ERROR = "State E"
    """Error state; Short or powered off."""

    FAULT = "State F"
    """Fault state; Charger is not operational."""

    INVALID = "Invalid"
    """Invalid CP measured."""

    UNKNOWN = "Unknown"
    """CP signal cannot be measured."""


class PackageType(StrEnum):
    """Peblar package type."""

    FIRMWARE = "Firmware"
    """Firmware package."""

    CUSTOMIZATION = "Customization"
    """Customization package."""
