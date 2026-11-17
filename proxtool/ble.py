# Copyright 2026 A.S.D - Alexander Schwartz Developments
# SPDX-License-Identifier: Apache-2.0
"""Transport "ble": the computer's own Bluetooth, through bleak (Windows WinRT,
Linux BlueZ). See link.py for the interface.

`scan()` and `Tag()` below are shortcuts that use the *current* transport
(selected with `--via`), so callers do not care which radio is used.
"""
from __future__ import annotations

import asyncio
import time
from typing import Dict, Optional

from . import link as L
from . import protocol as P

try:
    from bleak import BleakClient, BleakScanner
except ImportError:  # pragma: no cover - tests run without bleak
    BleakClient = BleakScanner = None


def _need_bleak() -> None:
    if BleakScanner is None:
        raise SystemExit("proxtool needs bleak: pip install bleak")


class BleakLink(L.Link):
    def __init__(self, client, address: str):
        self.client = client
        self.address = address

    @property
    def mtu(self) -> int:
        return getattr(self.client, "mtu_size", 23)

    def has(self, uuid: str) -> bool:
        try:
            return self.client.services.get_characteristic(L.uuid_str(uuid)) is not None
        except Exception:
            return False

    async def read(self, uuid: str) -> bytes:
        try:
            return bytes(await self.client.read_gatt_char(L.uuid_str(uuid)))
        except Exception as e:
            if type(e).__name__.startswith("Bleak"):
                raise L.LinkError(f"read {uuid}: {e}") from e
            raise

    async def write(self, uuid: str, data: bytes, response: bool = True) -> None:
        try:
            await self.client.write_gatt_char(L.uuid_str(uuid), data, response=response)
        except Exception as e:
            if type(e).__name__.startswith("Bleak"):
                raise L.LinkError(f"write {uuid}: {e}") from e
            raise

    async def close(self) -> None:
        try:
            await self.client.disconnect()
        except Exception:
            pass


class BleakTransport(L.Transport):
    name = "ble"
    description = "this computer's Bluetooth"

    def __init__(self, **_opts):
        _need_bleak()
        self._scanner = None

    async def start_scan(self, on_beacon: L.BeaconCallback) -> None:
        if self._scanner is not None:
            return

        def cb(device, adv):
            b = P.parse_beacon(adv.manufacturer_data, adv.local_name)
            if b is not None:
                on_beacon(b, adv.rssi, time.time())
        self._scanner = BleakScanner(cb)
        await self._scanner.start()

    async def stop_scan(self) -> None:
        if self._scanner is not None:
            try:
                await self._scanner.stop()
            finally:
                self._scanner = None

    async def connect(self, address: str, timeout: float = 20.0) -> L.Link:
        # No cached GATT table: a firmware update changes it (Windows caches it per address).
        client = BleakClient(address, timeout=timeout, winrt={"use_cached_services": False})
        await client.connect()
        return BleakLink(client, address)

    async def find(self, addresses, seconds: float) -> Optional[str]:
        """Any advertiser at these addresses (also a tag in AppLoader mode)."""
        want = {a.upper() for a in addresses}
        end = time.time() + seconds
        while time.time() < end:
            for d in await BleakScanner.discover(timeout=3.0):
                if d.address.upper() in want:
                    return d.address
            await asyncio.sleep(0.2)
        return None


# ---- shortcuts through the current transport ----------------------------------------

async def scan(seconds: float, on_beacon: Optional[L.BeaconCallback] = None) -> Dict[str, tuple]:
    """Collect beacons for `seconds`: {uid: (beacon, rssi, wall)} (latest)."""
    return await L.current().scan(seconds, on_beacon)


def Tag(address: str, timeout: float = 20.0, **kw):
    from .tag import Tag as _Tag
    return _Tag(address, L.current(), timeout, **kw)
