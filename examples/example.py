# pylint: disable=W0621
"""Asynchronous Python client for Peblar EV chargers."""

import asyncio

from peblar import Peblar


async def main() -> None:
    """Show example of programmatically control a Peblar charger."""
    async with Peblar(host="192.168.1.123") as peblar:
        await peblar.login(password="Sup3rS3cr3t!")

        await peblar.identify()

        system_information = await peblar.system_information()
        print(system_information)


if __name__ == "__main__":
    asyncio.run(main())
