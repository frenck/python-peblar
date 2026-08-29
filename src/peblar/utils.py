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

    Peblar usually wraps errors in a JSON object holding a `statusmsg`
    field, but not always: some endpoints answer with a bare JSON string,
    and a few of those wrap it a second time. Anything that is not a
    readable sentence in the end is dropped, leaving the generic message.
    """
    try:
        payload = orjson.loads(content)
    except orjson.JSONDecodeError:
        return message

    if isinstance(payload, dict):
        reason = payload.get("statusmsg") or payload.get("StatusMsg")
    else:
        reason = payload

    # Some endpoints hand back a JSON string that itself holds JSON, so
    # peel until there is nothing left to decode.
    while isinstance(reason, str):
        try:
            unwrapped = orjson.loads(reason)
        except orjson.JSONDecodeError:
            # Not JSON any more, so this is the sentence itself.
            break

        if not isinstance(unwrapped, str):
            # Structured data rather than a sentence. Handing back the text
            # it was written as would put raw JSON in front of the user.
            return message

        reason = unwrapped

    if not isinstance(reason, str) or not reason:
        return message

    return f"{message}: {reason}"
