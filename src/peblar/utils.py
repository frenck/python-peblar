"""Asynchronous Python client for Peblar EV chargers."""

from functools import lru_cache

import orjson
from awesomeversion import AwesomeVersion


@lru_cache
def get_awesome_version(version: str) -> AwesomeVersion:
    """Return a cached AwesomeVersion object."""
    return AwesomeVersion(version)


def build_error_message(message: str, content: str) -> str:
    """Enrich an error message with the one the charger sent along.

    Peblar wraps errors in a JSON object holding a `statusmsg` field. Not
    every response follows that shape, so anything else is dropped and the
    caller is left with just the generic message.
    """
    try:
        payload = orjson.loads(content)
    except orjson.JSONDecodeError:
        return message

    if not isinstance(payload, dict):
        return message

    reason = payload.get("statusmsg") or payload.get("StatusMsg")
    if not isinstance(reason, str) or not reason:
        return message

    return f"{message}: {reason}"
