"""Benchmarks for mashumaro deserialization of Peblar responses.

These paths run once per scan interval when this client is embedded in
Home Assistant, so regressions compound quickly. We benchmark the four
models that dominate steady-state parsing cost:

- PeblarUserConfiguration: ~50 fields plus pre- and post-deserialize hooks
  (nested JSON unpacking, smart-charging mode inference).
- PeblarSystemInformation: ~40 fields, read once per integration startup
  but big enough to matter when the client is used in scripts.
- PeblarSystem: smaller but polled every scan interval in HA.
- PeblarMeter: smallest, polled every scan interval in HA.

Payloads are loaded once at module import so the timed function contains
only the ``from_json`` call, not the fixture-read cost.
"""

from __future__ import annotations

import pytest

from peblar.models import (
    PeblarMeter,
    PeblarSystem,
    PeblarSystemInformation,
    PeblarUserConfiguration,
)
from tests import load_fixture

USER_CONFIGURATION_PAYLOAD = load_fixture("user_configuration.json")
SYSTEM_INFORMATION_PAYLOAD = load_fixture("system_information.json")
SYSTEM_PAYLOAD = load_fixture("system.json")
METER_PAYLOAD = load_fixture("meter.json")


@pytest.mark.benchmark
def test_parse_user_configuration() -> None:
    """Benchmark user configuration parsing (biggest model, pre/post hooks)."""
    PeblarUserConfiguration.from_json(USER_CONFIGURATION_PAYLOAD)


@pytest.mark.benchmark
def test_parse_system_information() -> None:
    """Benchmark system information parsing (startup path)."""
    PeblarSystemInformation.from_json(SYSTEM_INFORMATION_PAYLOAD)


@pytest.mark.benchmark
def test_parse_system() -> None:
    """Benchmark Local REST API /system parsing (per-scan path)."""
    PeblarSystem.from_json(SYSTEM_PAYLOAD)


@pytest.mark.benchmark
def test_parse_meter() -> None:
    """Benchmark Local REST API /meter parsing (per-scan path)."""
    PeblarMeter.from_json(METER_PAYLOAD)
