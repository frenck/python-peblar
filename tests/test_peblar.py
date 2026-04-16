"""Tests for `peblar.peblar`."""

from __future__ import annotations

import orjson
import pytest
from aiohttp import ClientConnectionError, ClientSession
from aioresponses import aioresponses

from peblar import Peblar
from peblar.const import (
    AccessMode,
    PackageType,
    SmartChargingMode,
)
from peblar.exceptions import (
    PeblarAuthenticationError,
    PeblarConnectionError,
    PeblarConnectionTimeoutError,
    PeblarError,
)
from peblar.peblar import PeblarApi
from tests import load_fixture

HOST = "example.com"
BASE_URL = f"http://{HOST}/api/v1/"
API_BASE_URL = f"http://{HOST}/api/wlac/v1/"
IDENTIFY_URL = BASE_URL + "system/identify"
LOGIN_URL = BASE_URL + "auth/login"
SYSTEM_INFO_URL = BASE_URL + "system/info"
USER_CONFIG_URL = BASE_URL + "config/user"
CURRENT_VERSIONS_URL = BASE_URL + "system/software/automatic-update/current-versions"
AVAILABLE_VERSIONS_URL = (
    BASE_URL + "system/software/automatic-update/available-versions"
)
API_TOKEN_URL = BASE_URL + "config/api-token"
REBOOT_URL = BASE_URL + "system/reboot"
UPDATE_URL = BASE_URL + "system/software/automatic-update/update"

# Local REST API endpoints (/api/wlac/v1)
API_HEALTH_URL = API_BASE_URL + "health"
API_METER_URL = API_BASE_URL + "meter"
API_SYSTEM_URL = API_BASE_URL + "system"
API_EV_URL = API_BASE_URL + "evinterface"


def patched_fixture(filename: str, **overrides: object) -> str:
    """Load a JSON fixture and override top-level fields.

    Tests that need a response variant (e.g., ``LocalRestApiAllowed`` flipped
    to ``false``) pass the wire-format alias as the keyword argument:

        patched_fixture("user_configuration.json", LocalRestApiAllowed=False)
    """
    data = orjson.loads(load_fixture(filename))
    data.update(overrides)
    return orjson.dumps(data).decode()


# ---------------------------------------------------------------------------
# request() transport layer
# ---------------------------------------------------------------------------


async def test_identify() -> None:
    """Test the identify method issues a PUT to the charger."""
    with aioresponses() as mocked:
        mocked.put(IDENTIFY_URL, status=200, body="", content_type="text/plain")
        async with Peblar(host=HOST) as peblar:
            await peblar.identify()


async def test_request_with_shared_session() -> None:
    """Test a passed-in shared session is reused by the client."""
    with aioresponses() as mocked:
        mocked.put(IDENTIFY_URL, status=200, body="", content_type="text/plain")
        async with ClientSession() as session:
            peblar = Peblar(host=HOST, session=session)
            await peblar.identify()
            await peblar.close()


async def test_http_error400() -> None:
    """Test HTTP 400 responses are surfaced as PeblarError."""
    with aioresponses() as mocked:
        mocked.put(
            IDENTIFY_URL, status=400, body="OMG PUPPIES!", content_type="text/plain"
        )
        async with Peblar(host=HOST) as peblar:
            with pytest.raises(PeblarError):
                await peblar.identify()


async def test_http_error500() -> None:
    """Test HTTP 500 responses are surfaced as PeblarError."""
    with aioresponses() as mocked:
        mocked.put(
            IDENTIFY_URL,
            status=500,
            body="Internal Server Error",
            content_type="text/plain",
        )
        async with Peblar(host=HOST) as peblar:
            with pytest.raises(PeblarError):
                await peblar.identify()


async def test_unauthenticated_response() -> None:
    """Test HTTP 401 responses are surfaced as PeblarAuthenticationError."""
    with aioresponses() as mocked:
        mocked.put(IDENTIFY_URL, status=401, body="", content_type="text/plain")
        async with Peblar(host=HOST) as peblar:
            with pytest.raises(PeblarAuthenticationError):
                await peblar.identify()


async def test_timeout() -> None:
    """Test a request timeout is surfaced as PeblarConnectionTimeoutError.

    The three mocks match tenacity's three retry attempts: each attempt
    consumes one mock and each raises the same timeout, so the final
    attempt reraises the timeout as PeblarConnectionTimeoutError.
    """
    with aioresponses() as mocked:
        for _ in range(3):
            mocked.put(IDENTIFY_URL, exception=TimeoutError())
        async with Peblar(host=HOST) as peblar:
            with pytest.raises(PeblarConnectionTimeoutError):
                await peblar.identify()


async def test_connection_error_retries_and_raises() -> None:
    """Tenacity retries connection errors three times, then reraises."""
    with aioresponses() as mocked:
        for _ in range(3):
            mocked.put(IDENTIFY_URL, exception=ClientConnectionError("boom"))
        peblar = Peblar(host=HOST)
        try:
            with pytest.raises(PeblarConnectionError):
                await peblar.identify()
        finally:
            await peblar.close()


async def test_retry_then_success() -> None:
    """Tenacity retries on connection error and succeeds on second attempt."""
    with aioresponses() as mocked:
        mocked.put(IDENTIFY_URL, exception=ClientConnectionError("boom"))
        mocked.put(IDENTIFY_URL, status=200, body="", content_type="text/plain")
        async with Peblar(host=HOST) as peblar:
            await peblar.identify()


# ---------------------------------------------------------------------------
# High-level methods (JSON payloads parsed via mashumaro)
# ---------------------------------------------------------------------------


async def test_login() -> None:
    """Test login posts credentials to the login endpoint."""
    with aioresponses() as mocked:
        mocked.post(LOGIN_URL, status=200, body="", content_type="text/plain")
        async with Peblar(host=HOST) as peblar:
            await peblar.login(password="Sup3rS3cr3t!")


async def test_reboot() -> None:
    """Test reboot posts to the reboot endpoint."""
    with aioresponses() as mocked:
        mocked.post(REBOOT_URL, status=200, body="", content_type="text/plain")
        async with Peblar(host=HOST) as peblar:
            await peblar.reboot()


async def test_update_firmware() -> None:
    """Test update posts with the requested package type."""
    with aioresponses() as mocked:
        mocked.post(UPDATE_URL, status=200, body="", content_type="text/plain")
        async with Peblar(host=HOST) as peblar:
            await peblar.update(package_type=PackageType.FIRMWARE)


async def test_smart_charging_default() -> None:
    """Test smart charging PATCHes the user config with the requested mode."""
    with aioresponses() as mocked:
        mocked.patch(USER_CONFIG_URL, status=200, body="", content_type="text/plain")
        async with Peblar(host=HOST) as peblar:
            await peblar.smart_charging(SmartChargingMode.DEFAULT)


async def test_system_information() -> None:
    """Test system_information parses a full response into a dataclass."""
    with aioresponses() as mocked:
        mocked.get(
            SYSTEM_INFO_URL, status=200, body=load_fixture("system_information.json")
        )
        async with Peblar(host=HOST) as peblar:
            info = await peblar.system_information()
    assert info.hostname == "PBLR-0000001"
    assert info.product_model_name == "WLAC1-H11R0WE0ICR00"
    assert info.hardware_max_current == 16


async def test_user_configuration_default_mode() -> None:
    """Test user_configuration parses a response and infers DEFAULT smart charging."""
    with aioresponses() as mocked:
        mocked.get(
            USER_CONFIG_URL, status=200, body=load_fixture("user_configuration.json")
        )
        async with Peblar(host=HOST) as peblar:
            config = await peblar.user_configuration()
    assert config.time_zone == "Europe/Amsterdam"
    assert config.smart_charging == SmartChargingMode.DEFAULT


async def test_user_configuration_scheduled_mode() -> None:
    """Test user_configuration infers SCHEDULED when scheduled_charging_enabled."""
    with aioresponses() as mocked:
        mocked.get(
            USER_CONFIG_URL,
            status=200,
            body=load_fixture("user_configuration_scheduled.json"),
        )
        async with Peblar(host=HOST) as peblar:
            config = await peblar.user_configuration()
    assert config.smart_charging == SmartChargingMode.SCHEDULED


async def test_current_versions() -> None:
    """Test current_versions parses the versions payload."""
    with aioresponses() as mocked:
        mocked.get(
            CURRENT_VERSIONS_URL, status=200, body=load_fixture("versions_current.json")
        )
        async with Peblar(host=HOST) as peblar:
            versions = await peblar.current_versions()
    assert versions.firmware == "1.9.0+1+WL-1"
    assert versions.customization == "Peblar-1.14"
    assert versions.firmware_version is not None
    assert str(versions.firmware_version) == "1.9.0"


async def test_available_versions() -> None:
    """Test available_versions parses the versions payload."""
    with aioresponses() as mocked:
        mocked.get(
            AVAILABLE_VERSIONS_URL,
            status=200,
            body=load_fixture("versions_available.json"),
        )
        async with Peblar(host=HOST) as peblar:
            versions = await peblar.available_versions()
    assert versions.firmware == "1.9.0+1+WL-1"


async def test_api_token() -> None:
    """Test api_token returns the parsed token."""
    with aioresponses() as mocked:
        mocked.get(API_TOKEN_URL, status=200, body=load_fixture("api_token.json"))
        async with Peblar(host=HOST) as peblar:
            token = await peblar.api_token()
    assert token == "0" * 64


async def test_api_token_generate_new() -> None:
    """Test api_token with generate_new_api_token posts then fetches."""
    with aioresponses() as mocked:
        mocked.post(API_TOKEN_URL, status=200, body="", content_type="text/plain")
        mocked.get(API_TOKEN_URL, status=200, body=load_fixture("api_token.json"))
        async with Peblar(host=HOST) as peblar:
            token = await peblar.api_token(generate_new_api_token=True)
    assert token == "0" * 64


# ---------------------------------------------------------------------------
# rest_api() / modbus_api() flow
# ---------------------------------------------------------------------------


async def test_rest_api_disallowed() -> None:
    """Test rest_api raises when the charger disallows the local REST API."""
    body = patched_fixture("user_configuration.json", LocalRestApiAllowed=False)
    with aioresponses() as mocked:
        mocked.get(USER_CONFIG_URL, status=200, body=body)
        async with Peblar(host=HOST) as peblar:
            with pytest.raises(PeblarError, match="not allowed"):
                await peblar.rest_api()


async def test_rest_api_disabled() -> None:
    """Test rest_api raises when the local REST API is disabled."""
    body = patched_fixture("user_configuration.json", LocalRestApiEnable=False)
    with aioresponses() as mocked:
        mocked.get(USER_CONFIG_URL, status=200, body=body)
        async with Peblar(host=HOST) as peblar:
            with pytest.raises(PeblarError, match="not enabled"):
                await peblar.rest_api()


async def test_rest_api_enable_flow() -> None:
    """Test rest_api toggles the API on via PATCH when currently disabled."""
    body = patched_fixture("user_configuration.json", LocalRestApiEnable=False)
    with aioresponses() as mocked:
        mocked.get(USER_CONFIG_URL, status=200, body=body)
        mocked.patch(USER_CONFIG_URL, status=200, body="", content_type="text/plain")
        mocked.get(API_TOKEN_URL, status=200, body=load_fixture("api_token.json"))
        async with Peblar(host=HOST) as peblar:
            api = await peblar.rest_api(enable=True)
            await api.close()
    assert api.token == "0" * 64


async def test_modbus_api_disallowed() -> None:
    """Test modbus_api raises when the charger disallows Modbus."""
    body = patched_fixture("user_configuration.json", ModbusServerAllowed=False)
    with aioresponses() as mocked:
        mocked.get(USER_CONFIG_URL, status=200, body=body)
        async with Peblar(host=HOST) as peblar:
            with pytest.raises(PeblarError, match="not allowed"):
                await peblar.modbus_api(access_mode=AccessMode.READ_WRITE)


async def test_modbus_api_change_access_mode() -> None:
    """Test modbus_api PATCHes user config when the access mode differs."""
    body = patched_fixture(
        "user_configuration.json",
        ModbusServerAccessMode=AccessMode.READ_ONLY.value,
    )
    with aioresponses() as mocked:
        mocked.get(USER_CONFIG_URL, status=200, body=body)
        mocked.patch(USER_CONFIG_URL, status=200, body="", content_type="text/plain")
        async with Peblar(host=HOST) as peblar:
            await peblar.modbus_api(access_mode=AccessMode.READ_WRITE)


# ---------------------------------------------------------------------------
# PeblarApi (the /api/wlac/v1 Local REST API)
# ---------------------------------------------------------------------------


async def test_api_health() -> None:
    """Test PeblarApi.health parses a health response."""
    with aioresponses() as mocked:
        mocked.get(API_HEALTH_URL, status=200, body=load_fixture("health.json"))
        async with PeblarApi(host=HOST, token="t") as api:
            health = await api.health()
    assert health.access_mode == AccessMode.READ_WRITE


async def test_api_meter() -> None:
    """Test PeblarApi.meter parses a meter response."""
    with aioresponses() as mocked:
        mocked.get(API_METER_URL, status=200, body=load_fixture("meter.json"))
        async with PeblarApi(host=HOST, token="t") as api:
            meter = await api.meter()
    assert meter.power_total == 0
    assert meter.current_total == 0


async def test_api_system() -> None:
    """Test PeblarApi.system parses a system response."""
    with aioresponses() as mocked:
        mocked.get(API_SYSTEM_URL, status=200, body=load_fixture("system.json"))
        async with PeblarApi(host=HOST, token="t") as api:
            system = await api.system()
    assert system.uptime == 3514985
    assert system.phase_count == 3


async def test_api_ev_interface_read() -> None:
    """Test PeblarApi.ev_interface parses an EV interface response."""
    with aioresponses() as mocked:
        mocked.get(API_EV_URL, status=200, body=load_fixture("ev_interface.json"))
        async with PeblarApi(host=HOST, token="t") as api:
            ev = await api.ev_interface()
    assert ev.charge_current_limit == 16000


async def test_api_ev_interface_patch_then_read() -> None:
    """Test PeblarApi.ev_interface PATCHes then reads when params are provided."""
    with aioresponses() as mocked:
        mocked.patch(API_EV_URL, status=200, body="", content_type="text/plain")
        mocked.get(API_EV_URL, status=200, body=load_fixture("ev_interface.json"))
        async with PeblarApi(host=HOST, token="t") as api:
            ev = await api.ev_interface(charge_current_limit=10000)
    assert ev.charge_current_limit == 16000


async def test_api_401_authentication_error() -> None:
    """Test PeblarApi 401 is surfaced as PeblarAuthenticationError."""
    with aioresponses() as mocked:
        mocked.get(API_HEALTH_URL, status=401, body="", content_type="text/plain")
        async with PeblarApi(host=HOST, token="t") as api:
            with pytest.raises(PeblarAuthenticationError):
                await api.health()
