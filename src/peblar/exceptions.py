"""Asynchronous Python client for Peblar EV chargers."""


class PeblarError(Exception):
    """Generic Peblar exception."""


class PeblarConnectionError(PeblarError):
    """Peblar connection exception."""


class PeblarConnectionTimeoutError(PeblarConnectionError):
    """Peblar connection timeout exception."""


class PeblarResponseError(PeblarError):
    """Peblar unexpected response exception."""


class PeblarAuthenticationError(PeblarResponseError):
    """Peblar authentication exception."""


class PeblarBadRequestError(PeblarResponseError):
    """Peblar bad request (HTTP 400) exception."""


class PeblarRateLimitError(PeblarResponseError):
    """Peblar rate limit exception.

    The local REST API allows 5 requests per second, with bursts up to 10.
    Exceeding that gets you an HTTP 429 until the charger calms down again.
    """


class PeblarUnsupportedFirmwareVersionError(PeblarError):
    """Peblar unsupported version exception."""
