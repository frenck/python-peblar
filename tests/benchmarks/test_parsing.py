"""Benchmarks for mashumaro deserialization of Peblar responses.

These paths run once per scan interval when this client is embedded in
Home Assistant, so regressions compound quickly. We benchmark the three
models that dominate steady-state parsing cost:

- PeblarUserConfiguration: ~50 fields plus pre- and post-deserialize hooks
  (nested JSON unpacking, smart-charging mode inference).
- PeblarSystemInformation: ~40 fields, read once per integration startup
  but big enough to matter when the client is used in scripts.
- PeblarMeter: small but polled every scan interval in HA.
"""

from __future__ import annotations

import pytest

from peblar.models import (
    PeblarMeter,
    PeblarSystem,
    PeblarSystemInformation,
    PeblarUserConfiguration,
)
from tests.factories import (
    make_meter,
    make_system,
    make_system_information,
    user_configuration_json,
)


@pytest.fixture(scope="module")
def user_configuration_payload() -> str:
    """Return a realistic PeblarUserConfiguration JSON payload."""
    return user_configuration_json()


@pytest.fixture(scope="module")
def system_information_payload() -> str:
    """Return a realistic PeblarSystemInformation JSON payload."""
    return make_system_information().to_json()


@pytest.fixture(scope="module")
def system_payload() -> str:
    """Return a realistic PeblarSystem JSON payload."""
    return make_system().to_json()


@pytest.fixture(scope="module")
def meter_payload() -> str:
    """Return a realistic PeblarMeter JSON payload."""
    return make_meter().to_json()


@pytest.mark.benchmark
def test_parse_user_configuration(user_configuration_payload: str) -> None:
    """Benchmark user configuration parsing (biggest model, pre/post hooks)."""
    PeblarUserConfiguration.from_json(user_configuration_payload)


@pytest.mark.benchmark
def test_parse_system_information(system_information_payload: str) -> None:
    """Benchmark system information parsing (startup path)."""
    PeblarSystemInformation.from_json(system_information_payload)


@pytest.mark.benchmark
def test_parse_system(system_payload: str) -> None:
    """Benchmark Local REST API /system parsing (per-scan path)."""
    PeblarSystem.from_json(system_payload)


@pytest.mark.benchmark
def test_parse_meter(meter_payload: str) -> None:
    """Benchmark Local REST API /meter parsing (per-scan path)."""
    PeblarMeter.from_json(meter_payload)
