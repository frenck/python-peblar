"""Benchmarks for `peblar` model deserialization.

These benchmarks measure the performance of parsing the JSON payloads
returned by Peblar EV chargers into their mashumaro-backed dataclasses.
Deserialization is on the hot path of every API call, so it is a good
representative workload to track for performance regressions.
"""

from __future__ import annotations

import pytest

from peblar.models import (
    PeblarEVInterface,
    PeblarHealth,
    PeblarMeter,
    PeblarSystem,
    PeblarSystemInformation,
    PeblarUserConfiguration,
    PeblarVersions,
)
from tests import load_fixture


@pytest.mark.benchmark
def test_benchmark_system_information() -> None:
    """Benchmark deserialization of the full system information payload."""
    payload = load_fixture("system_information.json")
    PeblarSystemInformation.from_json(payload)


@pytest.mark.benchmark
def test_benchmark_user_configuration() -> None:
    """Benchmark deserialization of the user configuration payload.

    This is the largest and most complex model, with nested JSON parsing
    in the pre-deserialize hook and smart-charging inference in the
    post-deserialize hook.
    """
    payload = load_fixture("user_configuration.json")
    PeblarUserConfiguration.from_json(payload)


@pytest.mark.benchmark
def test_benchmark_versions() -> None:
    """Benchmark deserialization of the versions payload."""
    payload = load_fixture("versions_current.json")
    PeblarVersions.from_json(payload)


@pytest.mark.benchmark
def test_benchmark_health() -> None:
    """Benchmark deserialization of the health payload."""
    payload = load_fixture("health.json")
    PeblarHealth.from_json(payload)


@pytest.mark.benchmark
def test_benchmark_system() -> None:
    """Benchmark deserialization of the local REST API system payload."""
    payload = load_fixture("system.json")
    PeblarSystem.from_json(payload)


@pytest.mark.benchmark
def test_benchmark_meter() -> None:
    """Benchmark deserialization of the meter payload."""
    payload = load_fixture("meter.json")
    PeblarMeter.from_json(payload)


@pytest.mark.benchmark
def test_benchmark_ev_interface() -> None:
    """Benchmark deserialization of the EV interface payload."""
    payload = load_fixture("ev_interface.json")
    PeblarEVInterface.from_json(payload)
