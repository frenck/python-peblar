"""Benchmarks for Peblar model serialization and deserialization."""

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

SYSTEM_INFORMATION_JSON = (
    b'{"BopCalIGainA":1000,"BopCalIGainB":1000,"BopCalIGainC":1000,'
    b'"CanChangeChargingPhases":true,"CanChargeSinglePhase":true,'
    b'"CanChargeThreePhases":true,"CustomerId":"peblar",'
    b'"CustomerUpdatePackagePubKey":"abc123","EthMacAddr":"00:11:22:33:44:55",'
    b'"FwIdent":"1.6.1+1+WL-1.0","Hostname":"peblar-012345",'
    b'"HwFixedCableRating":32,"HwFwCompat":"A","HwHasBop":true,'
    b'"HwHasBuzzer":true,"HwHasEichrechtLaserMarking":false,'
    b'"HwHasEthernet":true,"HwHasLed":true,"HwHasLte":false,'
    b'"HwHasMeter":true,"HwHasMeterDisplay":false,"HwHasPlc":false,'
    b'"HwHasRfid":true,"HwHasRs485":true,"HwHasSocket":false,'
    b'"HwHasTpm":true,"HwHasWlan":true,"HwMaxCurrent":32,'
    b'"HwOneOrThreePhase":3,"MainboardPn":"MB-001","MainboardSn":"SN-001",'
    b'"MeterCalIGainA":1000,"MeterCalIGainB":1000,"MeterCalIGainC":1000,'
    b'"MeterCalIRmsOffsetA":0,"MeterCalIRmsOffsetB":0,"MeterCalIRmsOffsetC":0,'
    b'"MeterCalPhaseA":0,"MeterCalPhaseB":0,"MeterCalPhaseC":0,'
    b'"MeterCalVGainA":1000,"MeterCalVGainB":1000,"MeterCalVGainC":1000,'
    b'"MeterFwIdent":"2.0.0","ProductModelName":"Peblar Home",'
    b'"ProductPn":"PB-001","ProductSn":"PS-001",'
    b'"ProductVendorName":"Peblar","WlanApMacAddr":"00:11:22:33:44:56",'
    b'"WlanStaMacAddr":"00:11:22:33:44:57"}'
)

USER_CONFIGURATION_JSON = (
    b'{"BopFallbackCurrent":10,"BopHomeWizardAddress":"",'
    b'"BopSource":"None","BopSourceParameters":"{}",'
    b'"ConnectedPhases":3,"CurrentCtrlBopCtType":"100A",'
    b'"CurrentCtrlBopEnable":false,"CurrentCtrlBopFuseRating":25,'
    b'"CurrentCtrlFixedChargeCurrentLimit":16,"GroundMonitoring":true,'
    b'"GroupLoadBalancingEnable":false,"GroupLoadBalancingFallbackCurrent":6,'
    b'"GroupLoadBalancingGroupId":0,"GroupLoadBalancingInterface":"Wlan",'
    b'"GroupLoadBalancingMaxCurrent":32,"GroupLoadBalancingRole":"Standalone",'
    b'"HmiBuzzerVolume":3,"HmiLedIntensityManual":50,"HmiLedIntensityMax":100,'
    b'"HmiLedIntensityMin":10,"HmiLedIntensityMode":"Auto",'
    b'"LocalRestApiAccessMode":"ReadWrite","LocalRestApiAllowed":true,'
    b'"LocalRestApiEnable":true,"LocalSmartChargingAllowed":true,'
    b'"ModbusServerAccessMode":"ReadWrite","ModbusServerAllowed":true,'
    b'"ModbusServerEnable":false,"PhaseRotation":"L1-L2-L3",'
    b'"PowerLimitInputDi1Inverse":false,"PowerLimitInputDi1Limit":0,'
    b'"PowerLimitInputDi2Inverse":false,"PowerLimitInputDi2Limit":0,'
    b'"PowerLimitInputEnable":false,"PredefinedCpoName":"None",'
    b'"ScheduledChargingAllowed":true,"ScheduledChargingEnable":false,'
    b'"SeccOcppActive":false,"SeccOcppUri":"",'
    b'"SessionManagerChargeWithoutAuth":true,"SolarChargingAllowed":true,'
    b'"SolarChargingEnable":false,"SolarChargingMode":"MaxSolar",'
    b'"SolarChargingSource":"None","SolarChargingSourceParameters":"{}",'
    b'"TimeZone":"Europe/Amsterdam","UserDefinedChargeLimitCurrent":16,'
    b'"UserDefinedChargeLimitCurrentAllowed":true,'
    b'"UserDefinedHouseholdPowerLimit":0,'
    b'"UserDefinedHouseholdPowerLimitAllowed":true,'
    b'"UserDefinedHouseholdPowerLimitEnable":false,'
    b'"UserDefinedHouseholdPowerLimitSource":"None",'
    b'"UserKeepSocketLocked":false,"VDEPhaseImbalanceEnable":false,'
    b'"VDEPhaseImbalanceLimit":20,"WebIfUpdateHelper":true}'
)

METER_JSON = (
    b'{"CurrentPhase1":15000,"CurrentPhase2":15000,"CurrentPhase3":15000,'
    b'"EnergySession":5000,"EnergyTotal":150000,'
    b'"PowerPhase1":3450,"PowerPhase2":3450,"PowerPhase3":3450,'
    b'"PowerTotal":10350,"VoltagePhase1":230,"VoltagePhase2":230,'
    b'"VoltagePhase3":230}'
)

EV_INTERFACE_JSON = (
    b'{"ChargeCurrentLimit":32,"ChargeCurrentLimitActual":16,'
    b'"ChargeCurrentLimitSource":"Current limiter","CpState":"State C",'
    b'"Force1Phase":false}'
)

SYSTEM_JSON = (
    b'{"ActiveErrorCodes":[],"ActiveWarningCodes":[],'
    b'"CellularSignalStrength":null,"FirmwareVersion":"1.6.1+1+WL-1.0",'
    b'"Force1PhaseAllowed":true,"PhaseCount":3,"ProductPn":"PB-001",'
    b'"ProductSn":"PS-001","Uptime":86400,"WlanSignalStrength":-50}'
)

HEALTH_JSON = b'{"AccessMode":"ReadWrite","ApiVersion":"1.0.0"}'

VERSIONS_JSON = b'{"Customization":"Peblar-1.8","Firmware":"1.6.1+1+WL-1.0"}'


@pytest.mark.benchmark
def test_bench_system_information_deserialization(
    benchmark: pytest.BenchmarkFixture,
) -> None:
    """Benchmark PeblarSystemInformation deserialization."""

    @benchmark
    def _() -> PeblarSystemInformation:
        return PeblarSystemInformation.from_json(SYSTEM_INFORMATION_JSON)


@pytest.mark.benchmark
def test_bench_system_information_serialization(
    benchmark: pytest.BenchmarkFixture,
) -> None:
    """Benchmark PeblarSystemInformation serialization."""
    obj = PeblarSystemInformation.from_json(SYSTEM_INFORMATION_JSON)

    @benchmark
    def _() -> bytes:
        return obj.to_json()


@pytest.mark.benchmark
def test_bench_user_configuration_deserialization(
    benchmark: pytest.BenchmarkFixture,
) -> None:
    """Benchmark PeblarUserConfiguration deserialization."""

    @benchmark
    def _() -> PeblarUserConfiguration:
        return PeblarUserConfiguration.from_json(USER_CONFIGURATION_JSON)


@pytest.mark.benchmark
def test_bench_user_configuration_serialization(
    benchmark: pytest.BenchmarkFixture,
) -> None:
    """Benchmark PeblarUserConfiguration serialization."""
    obj = PeblarUserConfiguration.from_json(USER_CONFIGURATION_JSON)

    @benchmark
    def _() -> bytes:
        return obj.to_json()


@pytest.mark.benchmark
def test_bench_meter_deserialization(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark PeblarMeter deserialization."""

    @benchmark
    def _() -> PeblarMeter:
        return PeblarMeter.from_json(METER_JSON)


@pytest.mark.benchmark
def test_bench_meter_serialization(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark PeblarMeter serialization."""
    obj = PeblarMeter.from_json(METER_JSON)

    @benchmark
    def _() -> bytes:
        return obj.to_json()


@pytest.mark.benchmark
def test_bench_ev_interface_deserialization(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark PeblarEVInterface deserialization."""

    @benchmark
    def _() -> PeblarEVInterface:
        return PeblarEVInterface.from_json(EV_INTERFACE_JSON)


@pytest.mark.benchmark
def test_bench_system_deserialization(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark PeblarSystem deserialization."""

    @benchmark
    def _() -> PeblarSystem:
        return PeblarSystem.from_json(SYSTEM_JSON)


@pytest.mark.benchmark
def test_bench_health_deserialization(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark PeblarHealth deserialization."""

    @benchmark
    def _() -> PeblarHealth:
        return PeblarHealth.from_json(HEALTH_JSON)


@pytest.mark.benchmark
def test_bench_versions_deserialization(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark PeblarVersions deserialization."""

    @benchmark
    def _() -> PeblarVersions:
        return PeblarVersions.from_json(VERSIONS_JSON)
