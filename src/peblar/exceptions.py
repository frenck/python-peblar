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


class PeblarUnsupportedFirmwareVersionError(PeblarError):
    """Peblar unsupported version exception."""
