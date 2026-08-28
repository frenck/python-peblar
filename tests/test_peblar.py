"""Tests for `peblar.peblar`."""

from __future__ import annotations

from typing import cast

import orjson
import pytest
from aiohttp import ClientConnectionError, ClientSession
from aioresponses import aioresponses

from peblar import Peblar
from peblar.const import (
    AccessMode,
    ChargeLimiter,
    CPState,
    LedBrightness,
    LedIntensityMode,
    PackageType,
    SmartChargingMode,
    SolarChargingMode,
    SoundVolume,
)
from peblar.exceptions import (
    PeblarAuthenticationError,
    PeblarBadRequestError,
    PeblarConnectionError,
    PeblarConnectionTimeoutError,
    PeblarError,
    PeblarRateLimitError,
    PeblarUnsupportedFirmwareVersionError,
)
from peblar.models import (
    PeblarEVInterface,
    PeblarMeter,
    PeblarScheduledCharging,
    PeblarScheduleSlot,
    PeblarSetUserConfiguration,
    PeblarSmartCharging,
    PeblarSystemInformation,
    PeblarUserConfiguration,
    PeblarVersions,
    resolve_led_brightness,
    resolve_smart_charging_mode,
)
from peblar.peblar import PeblarApi
from peblar.utils import build_error_message
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


def request_payload(mocked: aioresponses) -> dict[str, object]:
    """Return the decoded JSON body of the single request that was made."""
    requests = mocked.requests
    assert requests is not None
    call = next(iter(requests.values()))[0]
    return orjson.loads(call.kwargs["data"])


def mock_firmware_check(mocked: aioresponses) -> None:
    """Mock the firmware version lookup that rest_api() does up front."""
    mocked.get(
        CURRENT_VERSIONS_URL, status=200, body=load_fixture("versions_current.json")
    )


# ---------------------------------------------------------------------------
# request() transport layer
# ---------------------------------------------------------------------------
async def test_identify() -> None:
    """Test the identify method issues a PUT to the charger."""
    with aioresponses() as mocked:
        mocked.put(IDENTIFY_URL, status=200, body="", content_type="text/plain")
        async with Peblar(host=HOST) as peblar:
            await peblar.identify()


async def test_socket_unlock() -> None:
    """Test socket_unlock posts to the socket-unlock endpoint."""
    with aioresponses() as mocked:
        mocked.post(
            BASE_URL + "system/socket-unlock",
            status=200,
            body="",
            content_type="text/plain",
        )
        async with Peblar(host=HOST) as peblar:
            await peblar.socket_unlock()


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


async def test_update_user_configuration_household_limit() -> None:
    """Test setting the household power limit via update_user_configuration."""
    with aioresponses() as mocked:
        mocked.patch(USER_CONFIG_URL, status=200, body="", content_type="text/plain")
        async with Peblar(host=HOST) as peblar:
            await peblar.update_user_configuration(
                PeblarSetUserConfiguration(
                    user_defined_household_power_limit=7500,
                    user_defined_household_power_limit_enabled=True,
                ),
            )


async def test_socket_lock() -> None:
    """Test socket_lock PATCHes the user config endpoint."""
    with aioresponses() as mocked:
        mocked.patch(USER_CONFIG_URL, status=200, body="", content_type="text/plain")
        async with Peblar(host=HOST) as peblar:
            await peblar.socket_lock(locked=True)


async def test_set_buzzer_volume() -> None:
    """Test set_buzzer_volume PATCHes the user config endpoint."""
    with aioresponses() as mocked:
        mocked.patch(USER_CONFIG_URL, status=200, body="", content_type="text/plain")
        async with Peblar(host=HOST) as peblar:
            await peblar.set_buzzer_volume(volume=SoundVolume.MEDIUM)


async def test_set_led_brightness_auto() -> None:
    """Test set_led_brightness sends auto mode when AUTOMATIC is requested."""
    with aioresponses() as mocked:
        mocked.patch(USER_CONFIG_URL, status=200, body="", content_type="text/plain")
        async with Peblar(host=HOST) as peblar:
            await peblar.set_led_brightness(brightness=LedBrightness.AUTOMATIC)


async def test_set_led_brightness_fixed() -> None:
    """Test set_led_brightness sends fixed mode with manual value."""
    with aioresponses() as mocked:
        mocked.patch(USER_CONFIG_URL, status=200, body="", content_type="text/plain")
        async with Peblar(host=HOST) as peblar:
            await peblar.set_led_brightness(brightness=LedBrightness.MEDIUM)


async def test_update_user_configuration() -> None:
    """Test update_user_configuration PATCHes the user config endpoint."""
    with aioresponses() as mocked:
        mocked.patch(USER_CONFIG_URL, status=200, body="", content_type="text/plain")
        async with Peblar(host=HOST) as peblar:
            await peblar.update_user_configuration(
                PeblarSetUserConfiguration(user_defined_charge_limit_current=10),
            )


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
    assert config.led_brightness == LedBrightness.MEDIUM


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
        mock_firmware_check(mocked)
        mocked.get(USER_CONFIG_URL, status=200, body=body)
        async with Peblar(host=HOST) as peblar:
            with pytest.raises(PeblarError, match="not allowed"):
                await peblar.rest_api()


async def test_rest_api_disabled() -> None:
    """Test rest_api raises when the local REST API is disabled."""
    body = patched_fixture("user_configuration.json", LocalRestApiEnable=False)
    with aioresponses() as mocked:
        mock_firmware_check(mocked)
        mocked.get(USER_CONFIG_URL, status=200, body=body)
        async with Peblar(host=HOST) as peblar:
            with pytest.raises(PeblarError, match="not enabled"):
                await peblar.rest_api()


async def test_rest_api_enable_flow() -> None:
    """Test rest_api toggles the API on via PATCH when currently disabled."""
    body = patched_fixture("user_configuration.json", LocalRestApiEnable=False)
    with aioresponses() as mocked:
        mock_firmware_check(mocked)
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


async def test_api_ev_interface_lock_state() -> None:
    """Test lock_state is parsed from a socket charger response."""
    body = patched_fixture("ev_interface.json", LockState=True)
    with aioresponses() as mocked:
        mocked.get(API_EV_URL, status=200, body=body)
        async with PeblarApi(host=HOST, token="t") as api:
            ev = await api.ev_interface()
    assert ev.lock_state is True


async def test_api_ev_interface_lock_state_absent() -> None:
    """Test lock_state is None on fixed-cable chargers (field absent)."""
    with aioresponses() as mocked:
        mocked.get(API_EV_URL, status=200, body=load_fixture("ev_interface.json"))
        async with PeblarApi(host=HOST, token="t") as api:
            ev = await api.ev_interface()
    assert ev.lock_state is None


async def test_api_ev_interface_cp_state_invalid() -> None:
    """Test CPState invalid is parsed from a socket charger response."""
    body = patched_fixture("ev_interface_cpstate_invalid.json")
    with aioresponses() as mocked:
        mocked.get(API_EV_URL, status=200, body=body)
        async with PeblarApi(host=HOST, token="t") as api:
            ev = await api.ev_interface()
    assert ev.cp_state == CPState.INVALID


async def test_api_401_authentication_error() -> None:
    """Test PeblarApi 401 is surfaced as PeblarAuthenticationError."""
    with aioresponses() as mocked:
        mocked.get(API_HEALTH_URL, status=401, body="", content_type="text/plain")
        async with PeblarApi(host=HOST, token="t") as api:
            with pytest.raises(PeblarAuthenticationError):
                await api.health()


async def test_api_token_refresh_on_401() -> None:
    """Test PeblarApi refreshes the token and retries on a 401.

    Simulates a charger reboot that invalidates the API token. The first
    request returns 401, the token_refresh callback provides a fresh
    token, and the retried request succeeds.
    """

    async def fake_refresh() -> str:
        return "refreshed-token"

    with aioresponses() as mocked:
        # First call: 401 (stale token)
        mocked.get(API_HEALTH_URL, status=401, body="", content_type="text/plain")
        # Second call after refresh: success
        mocked.get(API_HEALTH_URL, status=200, body=load_fixture("health.json"))
        async with PeblarApi(
            host=HOST, token="stale-token", token_refresh=fake_refresh
        ) as api:
            health = await api.health()
    assert health.access_mode == AccessMode.READ_WRITE
    assert api.token == "refreshed-token"


async def test_api_token_refresh_still_fails() -> None:
    """Test PeblarApi raises after refresh if the retried request also 401s."""

    async def fake_refresh() -> str:
        return "also-bad-token"

    with aioresponses() as mocked:
        # First call: 401
        mocked.get(API_HEALTH_URL, status=401, body="", content_type="text/plain")
        # Retry after refresh: still 401
        mocked.get(API_HEALTH_URL, status=401, body="", content_type="text/plain")
        async with PeblarApi(
            host=HOST, token="stale", token_refresh=fake_refresh
        ) as api:
            with pytest.raises(PeblarAuthenticationError):
                await api.health()


async def test_api_401_without_refresh_callback() -> None:
    """Test PeblarApi 401 raises immediately when no token_refresh is set."""
    with aioresponses() as mocked:
        mocked.get(API_HEALTH_URL, status=401, body="", content_type="text/plain")
        async with PeblarApi(host=HOST, token="t") as api:
            with pytest.raises(PeblarAuthenticationError):
                await api.health()


async def test_peblar_login_stores_password_for_refresh() -> None:
    """Test that login() stores the password so rest_api() can refresh tokens."""
    with aioresponses() as mocked:
        mock_firmware_check(mocked)
        mocked.post(LOGIN_URL, status=200, body="", content_type="text/plain")
        mocked.get(
            USER_CONFIG_URL, status=200, body=load_fixture("user_configuration.json")
        )
        mocked.get(API_TOKEN_URL, status=200, body=load_fixture("api_token.json"))
        async with Peblar(host=HOST) as peblar:
            await peblar.login(password="test-pass")
            api = await peblar.rest_api()
            await api.close()
    assert api.token_refresh is not None


async def test_peblar_refresh_without_login_raises() -> None:
    """Test _refresh_api_token raises when login() was never called."""
    peblar = Peblar(host=HOST)
    with pytest.raises(PeblarAuthenticationError, match="no password stored"):
        await peblar._refresh_api_token()  # pylint: disable=protected-access
    await peblar.close()


async def test_api_timeout() -> None:
    """Test PeblarApi request timeout is surfaced as PeblarConnectionTimeoutError."""
    with aioresponses() as mocked:
        for _ in range(3):
            mocked.get(API_HEALTH_URL, exception=TimeoutError())
        async with PeblarApi(host=HOST, token="t") as api:
            with pytest.raises(PeblarConnectionTimeoutError):
                await api.health()


async def test_api_connection_error() -> None:
    """Test PeblarApi connection error retries and raises."""
    with aioresponses() as mocked:
        for _ in range(3):
            mocked.get(API_HEALTH_URL, exception=ClientConnectionError("boom"))
        async with PeblarApi(host=HOST, token="t") as api:
            with pytest.raises(PeblarConnectionError):
                await api.health()


# ---------------------------------------------------------------------------
# rest_api() / modbus_api() noop branches
# ---------------------------------------------------------------------------
async def test_rest_api_already_enabled_noop() -> None:
    """Test rest_api skips the PATCH when enable already matches current state."""
    body = load_fixture("user_configuration.json")
    with aioresponses() as mocked:
        mock_firmware_check(mocked)
        mocked.get(USER_CONFIG_URL, status=200, body=body)
        # No PATCH mock: if rest_api tries to PATCH, aioresponses raises ConnectionError
        mocked.get(API_TOKEN_URL, status=200, body=load_fixture("api_token.json"))
        async with Peblar(host=HOST) as peblar:
            api = await peblar.rest_api(enable=True)
            await api.close()


async def test_rest_api_access_mode_already_matches() -> None:
    """Test rest_api skips the PATCH when access_mode matches current state."""
    body = load_fixture("user_configuration.json")
    with aioresponses() as mocked:
        mock_firmware_check(mocked)
        mocked.get(USER_CONFIG_URL, status=200, body=body)
        mocked.get(API_TOKEN_URL, status=200, body=load_fixture("api_token.json"))
        async with Peblar(host=HOST) as peblar:
            # Fixture has ReadWrite, request ReadWrite: should be a noop
            api = await peblar.rest_api(access_mode=AccessMode.READ_WRITE)
            await api.close()


async def test_modbus_api_enable_already_matches() -> None:
    """Test modbus_api skips the PATCH when enable matches current state."""
    body = load_fixture("user_configuration.json")
    with aioresponses() as mocked:
        mocked.get(USER_CONFIG_URL, status=200, body=body)
        async with Peblar(host=HOST) as peblar:
            # Fixture has ModbusServerEnable=false, pass enable=False: noop
            await peblar.modbus_api(enable=False)


# ---------------------------------------------------------------------------
# Model deserialization edge cases
# ---------------------------------------------------------------------------


def test_system_information_whitelabel_missing_pubkey() -> None:
    """Test white-label chargers that omit CustomerUpdatePackagePubKey.

    Some white-label Peblar devices (e.g. ChargePoint-branded variants) do
    not include the CustomerUpdatePackagePubKey field. The model must parse
    successfully with the field set to None.
    """
    info = PeblarSystemInformation.from_json(
        load_fixture("system_information_whitelabel.json"),
    )
    assert info.customer_update_package_public_key is None
    assert info.hostname == "PBLR-0000001"


def test_system_information_missing_fixed_cable_rating() -> None:
    """Test socket chargers that omit HwFixedCableRating.

    Socket-variant Peblar chargers (e.g. Peblar Business) do not include
    the HwFixedCableRating field starting from firmware 1.8. The model
    must parse successfully with the field set to None.
    """
    body = patched_fixture("system_information.json")
    data = orjson.loads(body)
    del data["HwFixedCableRating"]
    info = PeblarSystemInformation.from_json(orjson.dumps(data))
    assert info.hardware_fixed_cable_rating is None


def test_versions_missing_fields() -> None:
    """Test PeblarVersions handles missing Customization and Firmware."""
    versions = PeblarVersions.from_json("{}")
    assert versions.customization is None
    assert versions.firmware is None
    assert versions.customization_version is None
    assert versions.firmware_version is None


def test_user_configuration_fast_solar() -> None:
    """Test user_configuration infers FAST_SOLAR (solar + MaxSolar mode)."""
    body = patched_fixture(
        "user_configuration.json",
        SolarChargingEnable=True,
        SolarChargingMode="MaxSolar",
    )
    config = PeblarUserConfiguration.from_json(body)
    assert config.smart_charging == SmartChargingMode.FAST_SOLAR


def test_user_configuration_smart_solar() -> None:
    """Test user_configuration infers SMART_SOLAR (solar + OptimizedSolar)."""
    body = patched_fixture(
        "user_configuration.json",
        SolarChargingEnable=True,
        SolarChargingMode="OptimizedSolar",
    )
    config = PeblarUserConfiguration.from_json(body)
    assert config.smart_charging == SmartChargingMode.SMART_SOLAR


def test_user_configuration_pure_solar() -> None:
    """Test user_configuration infers PURE_SOLAR (solar + PureSolar mode)."""
    body = patched_fixture(
        "user_configuration.json",
        SolarChargingEnable=True,
        SolarChargingMode="PureSolar",
    )
    config = PeblarUserConfiguration.from_json(body)
    assert config.smart_charging == SmartChargingMode.PURE_SOLAR


def test_user_configuration_led_brightness_auto() -> None:
    """Test user_configuration infers AUTOMATIC led_brightness when mode is Auto."""
    body = patched_fixture(
        "user_configuration.json",
        HmiLedIntensityMode="Auto",
    )
    config = PeblarUserConfiguration.from_json(body)
    assert config.led_brightness == LedBrightness.AUTOMATIC


def test_smart_charging_model_default() -> None:
    """Test PeblarSmartCharging post_init for DEFAULT mode."""
    obj = PeblarSmartCharging(smart_charging=SmartChargingMode.DEFAULT)
    assert obj.scheduled_charging_enable is False
    assert obj.solar_charging_enable is False


def test_smart_charging_model_scheduled() -> None:
    """Test PeblarSmartCharging post_init for SCHEDULED mode."""
    obj = PeblarSmartCharging(smart_charging=SmartChargingMode.SCHEDULED)
    assert obj.scheduled_charging_enable is True
    assert obj.solar_charging_enable is False


def test_smart_charging_model_fast_solar() -> None:
    """Test PeblarSmartCharging post_init for FAST_SOLAR mode."""
    obj = PeblarSmartCharging(smart_charging=SmartChargingMode.FAST_SOLAR)
    assert obj.solar_charging_enable is True
    assert obj.solar_charging_mode == SolarChargingMode.MAX_SOLAR


def test_smart_charging_model_smart_solar() -> None:
    """Test PeblarSmartCharging post_init for SMART_SOLAR mode."""
    obj = PeblarSmartCharging(smart_charging=SmartChargingMode.SMART_SOLAR)
    assert obj.solar_charging_enable is True
    assert obj.solar_charging_mode == SolarChargingMode.OPTIMIZED_SOLAR


def test_smart_charging_model_pure_solar() -> None:
    """Test PeblarSmartCharging post_init for PURE_SOLAR mode."""
    obj = PeblarSmartCharging(smart_charging=SmartChargingMode.PURE_SOLAR)
    assert obj.solar_charging_enable is True
    assert obj.solar_charging_mode == SolarChargingMode.PURE_SOLAR


# ---------------------------------------------------------------------------
# RFID token operations
# ---------------------------------------------------------------------------

STANDALONELIST_URL = BASE_URL + "config/auth/standalonelist"


async def test_rfid_tokens() -> None:
    """Test fetching the list of RFID tokens."""
    with aioresponses() as mocked:
        mocked.get(
            STANDALONELIST_URL,
            status=200,
            body=load_fixture("standalonelist.json"),
        )
        async with Peblar(host=HOST) as peblar:
            tokens = await peblar.rfid_tokens()
    assert len(tokens) == 2
    assert tokens[0].rfid_token_uid == "0123456789ABCD"
    assert tokens[0].rfid_token_description == "My RFID Card"
    assert tokens[1].rfid_token_uid == "0123456789ABCE"
    assert tokens[1].rfid_token_description == "My Other RFID Card"


async def test_add_rfid_token() -> None:
    """Test adding an RFID token to the standalone auth list."""
    with aioresponses() as mocked:
        mocked.post(
            STANDALONELIST_URL,
            status=200,
            body="",
            content_type="text/plain",
        )
        async with Peblar(host=HOST) as peblar:
            await peblar.add_rfid_token(
                rfid_token_uid="0123456789ABCD",
                rfid_token_description="My Charge Card",
            )


async def test_delete_rfid_token() -> None:
    """Test deleting an RFID token from the standalone auth list."""
    with aioresponses() as mocked:
        mocked.delete(
            STANDALONELIST_URL + "/0123456789ABCD",
            status=200,
            body="",
            content_type="text/plain",
        )
        async with Peblar(host=HOST) as peblar:
            await peblar.delete_rfid_token(uid="0123456789ABCD")


# ---------------------------------------------------------------------------
# Single phase chargers (home-assistant/core#179900)
# ---------------------------------------------------------------------------
async def test_api_meter_single_phase() -> None:
    """Test a single phase charger that omits the phase 2 and 3 fields."""
    with aioresponses() as mocked:
        mocked.get(
            API_METER_URL, status=200, body=load_fixture("meter_single_phase.json")
        )
        async with PeblarApi(host=HOST, token="t") as api:
            meter = await api.meter()

    assert meter.current_phase_1 == 0
    assert meter.current_phase_2 is None
    assert meter.current_phase_3 is None
    assert meter.power_phase_2 is None
    assert meter.power_phase_3 is None
    assert meter.voltage_phase_1 == 219
    assert meter.voltage_phase_2 is None
    assert meter.energy_total == 39479


def test_meter_current_total_skips_absent_phases() -> None:
    """Test the total current ignores phases the charger does not have."""
    single = PeblarMeter.from_json(load_fixture("meter_single_phase.json"))
    assert single.current_total == 0

    single.current_phase_1 = 10212
    assert single.current_total == 10212

    three = PeblarMeter.from_json(load_fixture("meter.json"))
    assert three.current_total == 0
    three.current_phase_1 = 100
    three.current_phase_2 = 200
    three.current_phase_3 = 300
    assert three.current_total == 600


async def test_api_system_single_phase() -> None:
    """Test a charger that omits the signal strength fields entirely."""
    with aioresponses() as mocked:
        mocked.get(
            API_SYSTEM_URL, status=200, body=load_fixture("system_single_phase.json")
        )
        async with PeblarApi(host=HOST, token="t") as api:
            system = await api.system()

    assert system.phase_count == 1
    assert system.force_single_phase_allowed is False
    assert system.wlan_signal_strength is None
    assert system.cellular_signal_strength is None


# Transparent re-login (home-assistant/core#172604, #173297)
# ---------------------------------------------------------------------------
async def test_relogin_on_401_after_session_expiry() -> None:
    """Test a forgotten session is recovered without bothering the user."""
    with aioresponses() as mocked:
        mocked.post(LOGIN_URL, status=204, body="", content_type="text/plain")
        # The charger forgot the session, for example after a reboot.
        mocked.get(USER_CONFIG_URL, status=401, body="", content_type="text/plain")
        # Logging back in, then the retried request.
        mocked.post(LOGIN_URL, status=204, body="", content_type="text/plain")
        mocked.get(
            USER_CONFIG_URL, status=200, body=load_fixture("user_configuration.json")
        )

        async with Peblar(host=HOST) as peblar:
            await peblar.login(password="test-pass")
            config = await peblar.user_configuration()

    assert config.local_rest_api_allowed is True


async def test_relogin_only_retries_once() -> None:
    """Test a charger that keeps rejecting the session gives up after one retry."""
    with aioresponses() as mocked:
        mocked.post(LOGIN_URL, status=204, body="", content_type="text/plain")
        mocked.get(USER_CONFIG_URL, status=401, body="", content_type="text/plain")
        mocked.post(LOGIN_URL, status=204, body="", content_type="text/plain")
        mocked.get(USER_CONFIG_URL, status=401, body="", content_type="text/plain")

        async with Peblar(host=HOST) as peblar:
            await peblar.login(password="test-pass")
            with pytest.raises(PeblarAuthenticationError):
                await peblar.user_configuration()


async def test_relogin_surfaces_a_changed_password() -> None:
    """Test a password changed on the charger still reaches the caller.

    The stored password no longer works, so the automatic re-login is
    itself rejected. That has to surface, otherwise Home Assistant never
    asks the user for the new one.
    """
    with aioresponses() as mocked:
        mocked.post(LOGIN_URL, status=204, body="", content_type="text/plain")
        mocked.get(USER_CONFIG_URL, status=401, body="", content_type="text/plain")
        # The charger no longer accepts the password we have stored.
        mocked.post(LOGIN_URL, status=401, body="", content_type="text/plain")

        async with Peblar(host=HOST) as peblar:
            await peblar.login(password="test-pass")
            with pytest.raises(PeblarAuthenticationError):
                await peblar.user_configuration()


async def test_login_401_does_not_loop() -> None:
    """Test a rejected login does not try to log in again to fix itself."""
    with aioresponses() as mocked:
        mocked.post(LOGIN_URL, status=204, body="", content_type="text/plain")
        mocked.post(LOGIN_URL, status=401, body="", content_type="text/plain")

        async with Peblar(host=HOST) as peblar:
            await peblar.login(password="test-pass")
            with pytest.raises(PeblarAuthenticationError):
                await peblar.login(password="wrong-pass")


async def test_no_relogin_without_a_stored_password() -> None:
    """Test a client that never logged in has nothing to retry with."""
    with aioresponses() as mocked:
        mocked.get(USER_CONFIG_URL, status=401, body="", content_type="text/plain")
        async with Peblar(host=HOST) as peblar:
            with pytest.raises(PeblarAuthenticationError):
                await peblar.user_configuration()


def test_user_configuration_parses_parameter_blobs() -> None:
    """Test JSON encoded parameter blobs come back as dictionaries.

    The charger sends these as JSON encoded strings and
    ``__pre_deserialize__`` unpacks them, so both have to be annotated as
    mappings. Annotating one as ``str`` handed back the repr of a dict.
    """
    config = PeblarUserConfiguration.from_json(
        load_fixture("user_configuration.json"),
    )
    assert config.bop_source_parameters == {"address": "redacted-host"}
    assert config.solar_charging_source_parameters == {"address": "redacted-host"}
    assert config.bop_source_parameters.get("address") == "redacted-host"


def test_user_configuration_empty_parameter_blobs() -> None:
    """Test an empty parameter blob still lands as an empty dictionary."""
    config = PeblarUserConfiguration.from_json(
        patched_fixture(
            "user_configuration.json",
            BopSourceParameters="",
            SolarChargingSourceParameters="",
        ),
    )
    assert config.bop_source_parameters == {}
    assert config.solar_charging_source_parameters == {}


# ---------------------------------------------------------------------------
# Rate limiting and charger supplied error messages
# ---------------------------------------------------------------------------
async def test_rate_limit_retries_and_raises() -> None:
    """Test a persistent HTTP 429 is retried and then surfaces."""
    with aioresponses() as mocked:
        for _ in range(3):
            mocked.get(SYSTEM_INFO_URL, status=429, body="", content_type="text/plain")
        async with Peblar(host=HOST) as peblar:
            with pytest.raises(PeblarRateLimitError, match="Rate limit exceeded"):
                await peblar.system_information()


async def test_rate_limit_then_success() -> None:
    """Test a single HTTP 429 is retried and then succeeds."""
    with aioresponses() as mocked:
        mocked.get(SYSTEM_INFO_URL, status=429, body="", content_type="text/plain")
        mocked.get(
            SYSTEM_INFO_URL, status=200, body=load_fixture("system_information.json")
        )
        async with Peblar(host=HOST) as peblar:
            info = await peblar.system_information()
    assert info.product_vendor_name == "Peblar"


async def test_api_rate_limit() -> None:
    """Test the local REST API surfaces HTTP 429 as a rate limit error."""
    with aioresponses() as mocked:
        for _ in range(3):
            mocked.get(API_METER_URL, status=429, body="", content_type="text/plain")
        async with PeblarApi(host=HOST, token="t") as api:
            with pytest.raises(PeblarRateLimitError, match="Rate limit exceeded"):
                await api.meter()


async def test_error_response_includes_charger_message() -> None:
    """Test the charger's own error message ends up in the exception."""
    with aioresponses() as mocked:
        mocked.get(
            API_SYSTEM_URL,
            status=500,
            body=orjson.dumps({"statusmsg": "An internal server error occurred"}),
        )
        async with PeblarApi(host=HOST, token="t") as api:
            with pytest.raises(PeblarError, match="An internal server error occurred"):
                await api.system()


async def test_error_response_without_message() -> None:
    """Test a non-JSON error body leaves the generic message intact."""
    with aioresponses() as mocked:
        mocked.get(API_SYSTEM_URL, status=500, body="oops", content_type="text/plain")
        async with PeblarApi(host=HOST, token="t") as api:
            with pytest.raises(PeblarError, match="Error occurred while communicating"):
                await api.system()


async def test_bad_request_includes_charger_message() -> None:
    """Test a rejected request carries the charger's reason along."""
    with aioresponses() as mocked:
        mocked.patch(
            API_EV_URL,
            status=400,
            body=orjson.dumps({"statusmsg": "ChargeCurrentLimit out of range"}),
        )
        async with PeblarApi(host=HOST, token="t") as api:
            with pytest.raises(
                PeblarBadRequestError, match="ChargeCurrentLimit out of range"
            ):
                await api.ev_interface(charge_current_limit=99999)


async def test_authentication_error_includes_charger_message() -> None:
    """Test an unauthorized response carries the charger's message along."""
    with aioresponses() as mocked:
        mocked.post(LOGIN_URL, status=401, body=orjson.dumps({"statusmsg": "Nope"}))
        async with Peblar(host=HOST) as peblar:
            with pytest.raises(PeblarAuthenticationError, match="Nope"):
                await peblar.login(password="wrong")


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ('{"statusmsg": "Nope"}', "Boom: Nope"),
        ('{"StatusMsg": "Nope"}', "Boom: Nope"),
        ('{"statusmsg": ""}', "Boom"),
        ('{"statusmsg": 42}', "Boom"),
        ("{}", "Boom"),
        ("[]", "Boom"),
        ("not json", "Boom"),
        ("", "Boom"),
    ],
)
def test_build_error_message(content: str, expected: str) -> None:
    """Test error bodies are only used when they carry a usable message."""
    assert build_error_message("Boom", content) == expected


@pytest.mark.parametrize("status", [400, 401, 429, 500])
async def test_undecodable_error_body_still_maps_to_a_peblar_error(
    status: int,
) -> None:
    """Test a body that is not valid UTF-8 does not escape the error mapping.

    The body is read before the status is checked, so a charger answering
    an error with a mangled body must still raise a PeblarError rather
    than a UnicodeDecodeError nobody is catching.
    """
    with aioresponses() as mocked:
        for _ in range(3):
            mocked.get(
                API_SYSTEM_URL,
                status=status,
                body=b"\xff\xfe not utf-8 \x80",
                content_type="application/json",
            )
        async with PeblarApi(host=HOST, token="t") as api:
            with pytest.raises(PeblarError):
                await api.system()


async def test_undecodable_success_body_is_replaced_not_raised() -> None:
    """Test undecodable bytes in a successful body do not blow up the read."""
    with aioresponses() as mocked:
        mocked.get(
            API_SYSTEM_URL,
            status=200,
            body=b'{"ActiveErrorCodes": [], "ActiveWarningCodes": [],'
            b'"CellularSignalStrength": null, "FirmwareVersion": "1.9.2\xff",'
            b'"Force1PhaseAllowed": true, "PhaseCount": 3, "ProductPn": "p",'
            b'"ProductSn": "s", "Uptime": 1, "WlanSignalStrength": null}',
            content_type="application/json",
        )
        async with PeblarApi(host=HOST, token="t") as api:
            system = await api.system()

    assert system.phase_count == 3
    assert system.firmware_version.startswith("1.9.2")


# ---------------------------------------------------------------------------
# Fields reported by newer firmware
# ---------------------------------------------------------------------------
def test_system_information_newer_firmware_fields() -> None:
    """Test hardware traits reported by newer firmware are picked up."""
    info = PeblarSystemInformation.from_json(
        load_fixture("system_information.json"),
    )
    assert info.hardware_has_four_pole_relay is False
    assert info.hardware_has_dual_socket is False
    assert info.hardware_has_shutter is False
    assert info.hardware_uk_compliant is False
    assert info.nor_flash is True


def test_user_configuration_newer_firmware_fields() -> None:
    """Test settings reported by newer firmware are picked up."""
    config = PeblarUserConfiguration.from_json(
        load_fixture("user_configuration.json"),
    )
    assert config.connect_hub_visibility is True
    assert config.custom_customer_id == ""
    assert config.iso15118_communication_enabled is False
    assert config.sbo_allowed is True
    assert config.sbo_enabled == "Enabled"
    assert config.session_download_allowed is True
    assert config.user_defined_household_power_limit_source_parameters == {}


def test_system_information_older_firmware_omits_new_fields() -> None:
    """Test firmware that does not report the new traits still parses."""
    data = orjson.loads(load_fixture("system_information.json"))
    for key in (
        "HwHas4pRelay",
        "HwHasDualSocket",
        "HwHasShutter",
        "HwUKCompliant",
        "NorFlash",
    ):
        del data[key]

    info = PeblarSystemInformation.from_dict(data)
    assert info.hardware_has_four_pole_relay is None
    assert info.hardware_has_dual_socket is None
    assert info.hardware_has_shutter is None
    assert info.hardware_uk_compliant is None
    assert info.nor_flash is None


def test_user_configuration_older_firmware_omits_new_fields() -> None:
    """Test firmware that does not report the new settings still parses."""
    data = orjson.loads(load_fixture("user_configuration.json"))
    for key in (
        "ConnectHubVisibility",
        "CustomCustomerId",
        "Iso15118CommunicationEnable",
        "SboAllowed",
        "SboEnabled",
        "SessionDownloadAllowed",
        "UserDefinedHouseholdPowerLimitSourceParameters",
    ):
        del data[key]

    config = PeblarUserConfiguration.from_dict(data)
    assert config.connect_hub_visibility is None
    assert config.custom_customer_id is None
    assert config.iso15118_communication_enabled is None
    assert config.sbo_allowed is None
    assert config.sbo_enabled is None
    assert config.session_download_allowed is None
    assert config.user_defined_household_power_limit_source_parameters == {}


def test_household_power_limit_source_parameters_are_decoded() -> None:
    """Test the household limit parameter blob is unpacked like the others."""
    config = PeblarUserConfiguration.from_json(
        patched_fixture(
            "user_configuration.json",
            UserDefinedHouseholdPowerLimitSourceParameters='{"address": "meter-1"}',
        ),
    )
    assert config.user_defined_household_power_limit_source_parameters == {
        "address": "meter-1"
    }


@pytest.mark.parametrize(
    ("blob", "expected"),
    [
        ('{"address": "meter-1"}', {"address": "meter-1"}),
        ({"address": "meter-1"}, {"address": "meter-1"}),
        ("", {}),
        (None, {}),
    ],
    ids=["encoded", "already-decoded", "empty-string", "null"],
)
def test_parameter_blob_shapes(blob: object, expected: dict[str, str]) -> None:
    """Test the parameter blobs survive every shape the charger sends.

    An already decoded mapping has to pass through untouched, so handing a
    previously parsed payload back in does not fail on a second decode.
    """
    data = orjson.loads(load_fixture("user_configuration.json"))
    data["BopSourceParameters"] = blob
    config = PeblarUserConfiguration.from_dict(data)
    assert config.bop_source_parameters == expected


# ---------------------------------------------------------------------------
# Expanded user configuration payload
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (
            SmartChargingMode.DEFAULT,
            {"ScheduledChargingEnable": False, "SolarChargingEnable": False},
        ),
        (
            SmartChargingMode.SCHEDULED,
            {"ScheduledChargingEnable": True, "SolarChargingEnable": False},
        ),
        (
            SmartChargingMode.FAST_SOLAR,
            {
                "ScheduledChargingEnable": False,
                "SolarChargingEnable": True,
                "SolarChargingMode": "MaxSolar",
            },
        ),
        (
            SmartChargingMode.SMART_SOLAR,
            {
                "ScheduledChargingEnable": False,
                "SolarChargingEnable": True,
                "SolarChargingMode": "OptimizedSolar",
            },
        ),
        (
            SmartChargingMode.PURE_SOLAR,
            {
                "ScheduledChargingEnable": False,
                "SolarChargingEnable": True,
                "SolarChargingMode": "PureSolar",
            },
        ),
    ],
)
def test_set_user_configuration_smart_charging(
    mode: SmartChargingMode,
    expected: dict[str, object],
) -> None:
    """Test the UI smart charging mode expands into the charger's fields."""
    payload = PeblarSetUserConfiguration(smart_charging=mode)
    assert orjson.loads(payload.to_json()) == expected


@pytest.mark.parametrize(
    ("brightness", "expected"),
    [
        (LedBrightness.AUTOMATIC, {"HmiLedIntensityMode": "Auto"}),
        (
            LedBrightness.OFF,
            {"HmiLedIntensityMode": "Fixed", "HmiLedIntensityManual": 0},
        ),
        (
            LedBrightness.MEDIUM,
            {"HmiLedIntensityMode": "Fixed", "HmiLedIntensityManual": 22},
        ),
        (
            LedBrightness.BRIGHT,
            {"HmiLedIntensityMode": "Fixed", "HmiLedIntensityManual": 100},
        ),
    ],
)
def test_set_user_configuration_led_brightness(
    brightness: LedBrightness,
    expected: dict[str, object],
) -> None:
    """Test the UI LED brightness expands into the charger's fields."""
    payload = PeblarSetUserConfiguration(led_brightness=brightness)
    assert orjson.loads(payload.to_json()) == expected


def test_set_user_configuration_omits_untouched_fields() -> None:
    """Test only the settings you actually set reach the charger."""
    payload = PeblarSetUserConfiguration(user_defined_charge_limit_current=10)
    assert orjson.loads(payload.to_json()) == {"UserDefinedChargeLimitCurrent": 10}


async def test_update_user_configuration_multiple_settings() -> None:
    """Test a single update can carry several settings at once."""
    with aioresponses() as mocked:
        mocked.patch(USER_CONFIG_URL, status=200, body="", content_type="text/plain")
        async with Peblar(host=HOST) as peblar:
            await peblar.update_user_configuration(
                PeblarSetUserConfiguration(
                    buzzer_volume=SoundVolume.LOW,
                    user_defined_charge_limit_current=10,
                    user_keep_socket_locked=True,
                    modbus_server_access_mode=AccessMode.READ_ONLY,
                ),
            )

    requests = mocked.requests
    assert requests is not None
    call = next(iter(requests.values()))[0]
    assert orjson.loads(call.kwargs["data"]) == {
        "HmiBuzzerVolume": 1,
        "ModbusServerAccessMode": "ReadOnly",
        "UserDefinedChargeLimitCurrent": 10,
        "UserKeepSocketLocked": True,
    }


def test_set_user_configuration_ui_fields_are_not_sent() -> None:
    """Test the replicated UI fields never reach the wire themselves."""
    payload = orjson.loads(
        PeblarSetUserConfiguration(
            smart_charging=SmartChargingMode.SCHEDULED,
            led_brightness=LedBrightness.OFF,
        ).to_json()
    )
    assert "smart_charging" not in payload
    assert "led_brightness" not in payload


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("default", (False, False, None)),
        ("scheduled", (True, False, None)),
        ("fast_solar", (False, True, SolarChargingMode.MAX_SOLAR)),
        ("smart_solar", (False, True, SolarChargingMode.OPTIMIZED_SOLAR)),
        ("pure_solar", (False, True, SolarChargingMode.PURE_SOLAR)),
    ],
)
def test_resolve_smart_charging_mode_accepts_plain_strings(
    mode: str,
    expected: tuple[bool, bool, SolarChargingMode | None],
) -> None:
    """Test a plain string means the same as the enum member.

    SmartChargingMode is a StrEnum, so comparing by identity would send a
    caller passing "scheduled" down the default path and quietly turn
    scheduled charging off instead of on.
    """
    assert resolve_smart_charging_mode(cast("SmartChargingMode", mode)) == expected
    assert resolve_smart_charging_mode(SmartChargingMode(mode)) == expected


def test_resolve_smart_charging_mode_rejects_unknown() -> None:
    """Test an unrecognised mode raises instead of disabling everything."""
    with pytest.raises(ValueError, match="Unknown smart charging mode"):
        resolve_smart_charging_mode(cast("SmartChargingMode", "nonsense"))


@pytest.mark.parametrize(
    ("brightness", "expected"),
    [
        (-1, (LedIntensityMode.AUTO, None)),
        (0, (LedIntensityMode.FIXED, 0)),
        (22, (LedIntensityMode.FIXED, 22)),
        (100, (LedIntensityMode.FIXED, 100)),
    ],
)
def test_resolve_led_brightness_accepts_plain_ints(
    brightness: int,
    expected: tuple[LedIntensityMode, int | None],
) -> None:
    """Test a plain int means the same as the enum member."""
    assert resolve_led_brightness(cast("LedBrightness", brightness)) == expected
    assert resolve_led_brightness(LedBrightness(brightness)) == expected


def test_resolve_led_brightness_rejects_unknown() -> None:
    """Test an intensity the UI has no name for never reaches the charger."""
    with pytest.raises(ValueError, match="not a valid LedBrightness"):
        resolve_led_brightness(cast("LedBrightness", 37))


def test_smart_charging_payload_from_plain_string() -> None:
    """Test the payload models accept a plain string just like the enum."""
    assert orjson.loads(
        PeblarSmartCharging(
            smart_charging=cast("SmartChargingMode", "scheduled")
        ).to_json()
    ) == orjson.loads(
        PeblarSmartCharging(smart_charging=SmartChargingMode.SCHEDULED).to_json()
    )
    assert orjson.loads(
        PeblarSetUserConfiguration(
            smart_charging=cast("SmartChargingMode", "pure_solar")
        ).to_json()
    ) == orjson.loads(
        PeblarSetUserConfiguration(
            smart_charging=SmartChargingMode.PURE_SOLAR
        ).to_json()
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"scheduled_charging_enabled": True},
        {"solar_charging_enabled": True},
        {"solar_charging_mode": SolarChargingMode.PURE_SOLAR},
    ],
    ids=["scheduled", "solar", "solar-mode"],
)
def test_smart_charging_shorthand_rejects_conflicts(kwargs: dict[str, object]) -> None:
    """Test the shorthand refuses to silently overwrite what you also set."""
    with pytest.raises(ValueError, match="not both"):
        PeblarSetUserConfiguration(
            smart_charging=SmartChargingMode.SCHEDULED,
            **kwargs,  # ty: ignore[invalid-argument-type]
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"led_intensity_mode": LedIntensityMode.AUTO},
        {"led_intensity_manual": 100},
    ],
    ids=["mode", "manual"],
)
def test_led_brightness_shorthand_rejects_conflicts(kwargs: dict[str, object]) -> None:
    """Test the LED shorthand refuses to silently overwrite what you set."""
    with pytest.raises(ValueError, match="not both"):
        PeblarSetUserConfiguration(
            led_brightness=LedBrightness.AUTOMATIC,
            **kwargs,  # ty: ignore[invalid-argument-type]
        )


def test_smart_charging_model_rejects_conflicts() -> None:
    """Test the same guard applies to the smart charging payload."""
    with pytest.raises(ValueError, match="not both"):
        PeblarSmartCharging(
            smart_charging=SmartChargingMode.SCHEDULED,
            solar_charging_enable=True,
        )


def test_shorthand_and_low_level_fields_work_on_their_own() -> None:
    """Test the guard only fires on a genuine overlap."""
    assert orjson.loads(
        PeblarSetUserConfiguration(led_brightness=LedBrightness.MEDIUM).to_json()
    ) == {"HmiLedIntensityManual": 22, "HmiLedIntensityMode": "Fixed"}
    assert orjson.loads(
        PeblarSetUserConfiguration(led_intensity_manual=50).to_json()
    ) == {"HmiLedIntensityManual": 50}
    assert orjson.loads(
        PeblarSetUserConfiguration(
            smart_charging=SmartChargingMode.SCHEDULED,
            buzzer_volume=SoundVolume.LOW,
        ).to_json()
    ) == {
        "HmiBuzzerVolume": 1,
        "ScheduledChargingEnable": True,
        "SolarChargingEnable": False,
    }


# ---------------------------------------------------------------------------
# Local REST API: firmware guard, PUT and charge session authorization
# ---------------------------------------------------------------------------
API_AUTHORIZATION_URL = API_BASE_URL + "authorization/charge-session"


async def test_rest_api_unsupported_firmware() -> None:
    """Test rest_api refuses firmware older than the local REST API itself."""
    body = patched_fixture("versions_current.json", Firmware="1.5.0+1+WL-1")
    with aioresponses() as mocked:
        mocked.get(CURRENT_VERSIONS_URL, status=200, body=body)
        async with Peblar(host=HOST) as peblar:
            with pytest.raises(
                PeblarUnsupportedFirmwareVersionError, match="requires firmware"
            ):
                await peblar.rest_api()


async def test_rest_api_unparsable_firmware_is_allowed() -> None:
    """Test an unreadable firmware version does not block the local REST API."""
    body = patched_fixture("versions_current.json", Firmware="")
    with aioresponses() as mocked:
        mocked.get(CURRENT_VERSIONS_URL, status=200, body=body)
        mocked.get(
            USER_CONFIG_URL, status=200, body=load_fixture("user_configuration.json")
        )
        mocked.get(API_TOKEN_URL, status=200, body=load_fixture("api_token.json"))
        async with Peblar(host=HOST) as peblar:
            api = await peblar.rest_api()
            await api.close()
    assert api.token == "0" * 64


async def test_api_set_ev_interface() -> None:
    """Test set_ev_interface PUTs and parses the returned state."""
    with aioresponses() as mocked:
        mocked.put(API_EV_URL, status=200, body=load_fixture("ev_interface.json"))
        async with PeblarApi(host=HOST, token="t") as api:
            ev_interface = await api.set_ev_interface(
                charge_current_limit=16000,
                force_single_phase=False,
            )
    assert ev_interface.charge_current_limit == 16000
    assert request_payload(mocked) == {
        "ChargeCurrentLimit": 16000,
        "Force1Phase": False,
    }


async def test_api_authorize_charge_session_by_token() -> None:
    """Test authorizing a charge session with a token UID."""
    with aioresponses() as mocked:
        mocked.post(
            API_AUTHORIZATION_URL, status=202, body="", content_type="text/plain"
        )
        async with PeblarApi(host=HOST, token="t") as api:
            await api.authorize_charge_session(token="0123456789ABCD")
    assert request_payload(mocked) == {
        "Method": "Rfid",
        "Token": "0123456789ABCD",
    }


async def test_api_authorize_charge_session_by_name() -> None:
    """Test authorizing a charge session with a token description."""
    with aioresponses() as mocked:
        mocked.post(
            API_AUTHORIZATION_URL, status=202, body="", content_type="text/plain"
        )
        async with PeblarApi(host=HOST, token="t") as api:
            await api.authorize_charge_session(name="My RFID Card")
    assert request_payload(mocked) == {
        "Method": "Rfid",
        "Name": "My RFID Card",
    }


@pytest.mark.parametrize(
    ("token", "name"),
    [
        (None, None),
        ("0123456789ABCD", "My RFID Card"),
    ],
    ids=["neither", "both"],
)
async def test_api_authorize_charge_session_needs_exactly_one(
    token: str | None,
    name: str | None,
) -> None:
    """Test the charge session payload insists on exactly one identifier."""
    async with PeblarApi(host=HOST, token="t") as api:
        with pytest.raises(ValueError, match="exactly one"):
            await api.authorize_charge_session(token=token, name=name)


def test_charge_limiter_reserved() -> None:
    """Test the reserved limiter source Peblar documents is recognised."""
    ev_interface = PeblarEVInterface.from_json(
        patched_fixture("ev_interface.json", ChargeCurrentLimitSource="Reserved"),
    )
    assert ev_interface.charge_current_limit_source is ChargeLimiter.RESERVED


# ---------------------------------------------------------------------------
# Device state endpoints
# ---------------------------------------------------------------------------
CONNECTOR_URL = BASE_URL + "system/connector"
NTP_SYNC_URL = BASE_URL + "system/ntp-sync"
WEB_INTERFACE_MODE_URL = BASE_URL + "system/web-interface-mode"
AUTH_STATUS_URL = BASE_URL + "auth/status"
LOGOUT_URL = BASE_URL + "auth/logout"


async def test_connector() -> None:
    """Test the connector endpoint reports what is plugged in."""
    with aioresponses() as mocked:
        mocked.get(CONNECTOR_URL, status=200, body=load_fixture("connector.json"))
        async with Peblar(host=HOST) as peblar:
            connector = await peblar.connector()
    assert connector.plugged_in_ev is False
    assert connector.plugged_in_evse is True


async def test_auth_status() -> None:
    """Test the session status endpoint."""
    with aioresponses() as mocked:
        mocked.get(AUTH_STATUS_URL, status=200, body=load_fixture("auth_status.json"))
        async with Peblar(host=HOST) as peblar:
            status = await peblar.auth_status()
    assert status.active is True
    assert status.version_hash == 2645344664


async def test_time_synced() -> None:
    """Test the NTP sync endpoint returns a plain boolean."""
    with aioresponses() as mocked:
        mocked.get(NTP_SYNC_URL, status=200, body=load_fixture("ntp_sync.json"))
        async with Peblar(host=HOST) as peblar:
            assert await peblar.time_synced() is True


async def test_web_interface_mode() -> None:
    """Test the web interface mode endpoint returns a plain string."""
    with aioresponses() as mocked:
        mocked.get(
            WEB_INTERFACE_MODE_URL,
            status=200,
            body=load_fixture("web_interface_mode.json"),
        )
        async with Peblar(host=HOST) as peblar:
            assert await peblar.web_interface_mode() == "dashboard"


async def test_logout_forgets_the_password() -> None:
    """Test logging out stops the client logging itself back in.

    The 401 retry added for the reauthentication issues relies on a stored
    password, so an explicit logout has to clear it or the very next
    request would undo the logout.
    """
    with aioresponses() as mocked:
        mocked.post(LOGIN_URL, status=204, body="", content_type="text/plain")
        mocked.post(LOGOUT_URL, status=204, body="", content_type="text/plain")
        mocked.get(USER_CONFIG_URL, status=401, body="", content_type="text/plain")

        async with Peblar(host=HOST) as peblar:
            await peblar.login(password="test-pass")
            await peblar.logout()
            with pytest.raises(PeblarAuthenticationError):
                await peblar.user_configuration()


# ---------------------------------------------------------------------------
# Statistics and the local charging schedule
# ---------------------------------------------------------------------------
SESSION_GRAPH_URL = BASE_URL + "statistics/session"
ENERGY_HISTORY_URL = BASE_URL + "statistics/history"
SCHEDULED_CHARGING_URL = BASE_URL + "config/scheduledcharging/schedules"


async def test_session_graph() -> None:
    """Test the charging session graph is parsed, newest measurement first."""
    with aioresponses() as mocked:
        mocked.get(
            SESSION_GRAPH_URL, status=200, body=load_fixture("session_graph.json")
        )
        async with Peblar(host=HOST) as peblar:
            graph = await peblar.session_graph()

    assert len(graph.data) == 3
    newest = graph.data[0]
    assert newest.average_power == [3450, 3410, 3480]
    assert newest.average_power_total == 10340
    assert newest.timestamp.year == 2026
    assert newest.timestamp.tzinfo is not None
    assert graph.data[-1].timestamp < newest.timestamp


async def test_energy_history() -> None:
    """Test the long term energy history is parsed."""
    with aioresponses() as mocked:
        mocked.get(
            ENERGY_HISTORY_URL, status=200, body=load_fixture("energy_history.json")
        )
        async with Peblar(host=HOST) as peblar:
            history = await peblar.energy_history()

    august = next(m for m in history.months if m.month == 8 and m.year == 2026)
    assert len(august.energy) == 31
    assert august.energy[30] == 12500
    year = next(y for y in history.years if y.year == 2026)
    assert len(year.energy) == 12
    assert year.energy[7] == 12500


async def test_scheduled_charging() -> None:
    """Test the local charging schedule is parsed for every weekday."""
    with aioresponses() as mocked:
        mocked.get(
            SCHEDULED_CHARGING_URL,
            status=200,
            body=load_fixture("scheduled_charging.json"),
        )
        async with Peblar(host=HOST) as peblar:
            schedule = await peblar.scheduled_charging()

    assert len(schedule.by_weekday) == 7
    assert schedule.monday[0].current_limit == 0
    assert schedule.monday[0].start_time == 0
    assert schedule.by_weekday[0] is schedule.monday
    assert schedule.by_weekday[6] is schedule.sunday


async def test_set_scheduled_charging() -> None:
    """Test writing the local charging schedule back to the charger."""
    schedule = PeblarScheduledCharging.from_json(
        load_fixture("scheduled_charging.json"),
    )
    schedule.monday = [
        PeblarScheduleSlot(current_limit=0, start_time=0),
        PeblarScheduleSlot(current_limit=10, start_time=23 * 60),
    ]

    with aioresponses() as mocked:
        mocked.post(
            SCHEDULED_CHARGING_URL, status=200, body="", content_type="text/plain"
        )
        async with Peblar(host=HOST) as peblar:
            await peblar.set_scheduled_charging(schedule)

    payload = request_payload(mocked)
    assert set(payload) == {
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    }
    assert payload["Monday"] == [
        {"CurrentLimit": 0, "StartTime": 0},
        {"CurrentLimit": 10, "StartTime": 1380},
    ]


# ---------------------------------------------------------------------------
# Autocharge vehicle list
# ---------------------------------------------------------------------------
VEHICLE_LIST_URL = BASE_URL + "config/auth/vehicle-standalonelist"


async def test_rfid_token_single() -> None:
    """Test fetching one RFID token by its UID."""
    with aioresponses() as mocked:
        mocked.get(
            STANDALONELIST_URL + "/0123456789ABCD",
            status=200,
            body=orjson.dumps(
                {
                    "RfidTokenUid": "0123456789ABCD",
                    "RfidTokenDescription": "My RFID Card",
                }
            ),
        )
        async with Peblar(host=HOST) as peblar:
            token = await peblar.rfid_token(uid="0123456789ABCD")
    assert token.rfid_token_description == "My RFID Card"


async def test_vehicle_tokens() -> None:
    """Test listing the autocharge vehicles."""
    with aioresponses() as mocked:
        mocked.get(
            VEHICLE_LIST_URL,
            status=200,
            body=load_fixture("vehicle_standalonelist.json"),
        )
        async with Peblar(host=HOST) as peblar:
            vehicles = await peblar.vehicle_tokens()
    assert len(vehicles) == 2
    assert vehicles[0].evcc_id == "NL-ABC-0123456789-1"
    assert vehicles[0].alias == "My EV"


@pytest.mark.parametrize("body", ["null", "{}", '{"VehicleTokens": null}'])
async def test_vehicle_tokens_empty(body: str) -> None:
    """Test a charger without autocharge hands back nothing usable.

    A charger with ISO 15118 disabled answers with a bare null rather
    than an empty list, which is what a real one was seen doing.
    """
    with aioresponses() as mocked:
        mocked.get(VEHICLE_LIST_URL, status=200, body=body)
        async with Peblar(host=HOST) as peblar:
            assert await peblar.vehicle_tokens() == []


async def test_add_vehicle_token() -> None:
    """Test adding a vehicle to the autocharge auth list."""
    with aioresponses() as mocked:
        mocked.post(VEHICLE_LIST_URL, status=200, body="", content_type="text/plain")
        async with Peblar(host=HOST) as peblar:
            await peblar.add_vehicle_token(
                evcc_id="NL-ABC-0123456789-1",
                alias="My EV",
            )
    assert request_payload(mocked) == {
        "EvccId": "NL-ABC-0123456789-1",
        "Alias": "My EV",
        "Authorize": True,
    }


async def test_delete_vehicle_token() -> None:
    """Test removing a vehicle from the autocharge auth list."""
    with aioresponses() as mocked:
        mocked.delete(
            VEHICLE_LIST_URL + "/NL-ABC-0123456789-1",
            status=200,
            body="",
            content_type="text/plain",
        )
        async with Peblar(host=HOST) as peblar:
            await peblar.delete_vehicle_token(evcc_id="NL-ABC-0123456789-1")
