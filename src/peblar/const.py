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
