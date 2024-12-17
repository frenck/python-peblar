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
    """Peblar connection exception."""


class PeblarUnsupportedFirmwareVersionError(PeblarError):
    """Peblar unsupported version exception."""
