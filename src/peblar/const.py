"""Asynchronous Python client for Peblar EV chargers."""

from enum import IntEnum, StrEnum

# Firmware version that introduced the local REST API.
MINIMUM_FIRMWARE_VERSION_LOCAL_REST_API = "1.6"


class AccessMode(StrEnum):
    """Peblar access mode."""

    READ_WRITE = "ReadWrite"
    """Read and write access."""

    READ_ONLY = "ReadOnly"
    """Read only access."""


class AuthorizationMethod(StrEnum):
    """Peblar charge session authorization method."""

    RFID = "Rfid"
    """Authorize using an RFID token from the standalone auth list."""


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


class LedBrightness(IntEnum):
    """Peblar LED brightness level."""

    AUTOMATIC = -1
    """Automatic LED brightness (follows ambient light)."""

    OFF = 0
    """LED off."""

    DIM = 2
    """Dim LED brightness."""

    MEDIUM = 22
    """Medium LED brightness."""

    BRIGHT = 100
    """Full LED brightness."""


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


class SessionState(StrEnum):
    """Peblar charging session state.

    Pushed over the websocket. These are the values the charger's own web
    interface knows how to render.
    """

    AVAILABLE = "available"
    """Idle and ready, nothing plugged in."""

    CHARGING = "charging"
    """Actively delivering energy to the EV."""

    FAULTED = "faulted"
    """The charger detected a fault."""

    FINISHING = "finishing"
    """The session is wrapping up."""

    PREPARING_AUTHORIZED = "preparingAuthorized"
    """Authorized, waiting for a cable."""

    PREPARING_PLUGGED_IN = "preparingPluggedIn"
    """Cable plugged in, waiting for authorization."""

    UNAVAILABLE = "unavailable"
    """Not available for charging."""


class WebsocketTopic(StrEnum):
    """Peblar websocket topics that take no parameters.

    The session status topic is per connector, see
    PeblarWebsocket.subscribe_session_status().
    """

    FIRMWARE_UPDATE_STATUS = "/system/fwupdate/status"
    """Progress of a running firmware update."""

    RFID_TOKEN_FOUND = "/rfid/tokenfound"  # noqa: S105
    """An RFID token was held against the reader."""

    STATUS_CHANGED = "/system/diagnostics/statuschanged"
    """An error or warning signal became active or cleared."""

    VEHICLE_TOKEN_FOUND = "/vehicle/tokenfound"  # noqa: S105
    """A vehicle identified itself for autocharge."""


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

    INTERNAL_POWER_LIMIT = "Internal power limit"
    """Charging limited by the internal power limit of the vehicle."""

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

    RESERVED = "Reserved"
    """Charging limited by a source reserved for internal development."""

    SOLAR_CHARGING = "Solar charging"
    """Charging limited by the maximum current due to solar charging."""


class CPState(StrEnum):
    """Peblar CP state."""

    NO_EV_CONNECTED = "State A"
    """No EV connected."""

    CHARGING_SUSPENDED = "State B"
    """EV connected, but charging suspended by either EV or charger."""

    CHARGING = "State C"
    """EV connected and charging."""

    CHARGING_VENTILATION = "State D"
    """EV connected and charging, but ventilation requested (not supported)."""

    ERROR = "State E"
    """Error, short to PE or powered off."""

    FAULT = "State F"
    """Fault detected by charger."""

    INVALID = "State Invalid"
    """Invalid CP level measured."""

    UNKNOWN = "unknown state"
    """CP signal cannot be measured."""


class PackageType(StrEnum):
    """Peblar package type."""

    FIRMWARE = "Firmware"
    """Firmware package."""

    CUSTOMIZATION = "Customization"
    """Customization package."""


# Order the charger expects its packages to be updated in. The web
# interface always sends Customization first, then Firmware, waiting for
# the charger to reboot in between.
PACKAGE_UPDATE_ORDER = (PackageType.CUSTOMIZATION, PackageType.FIRMWARE)
