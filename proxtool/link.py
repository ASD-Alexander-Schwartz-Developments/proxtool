# Copyright 2026 A.S.D - Alexander Schwartz Developments
# SPDX-License-Identifier: Apache-2.0
"""Transports: how proxtool reaches tags.

A transport scans for beacons and opens connections (Links) to tags. Everything
above it (tag commands, download, firmware update, bench check, the window) is
written against these two small interfaces, so tags can be reached through:

  ble   the computer's own Bluetooth (bleak)                       built in
  ncp   a USB Bluetooth adapter running Silicon Labs NCP firmware,
        e.g. a Thunderboard BG22 (pyBGAPI)                         built in
  ...   more from other packages, registered under the entry-point group
        "proxtool.transports" (e.g. the future RoostBox communicator)

A transport plugin is a class with the Transport methods below, constructed as
`cls(**options)`, where options come from `--via NAME[:OPTION]`.
"""
from __future__ import annotations

import time
from typing import Callable, Dict, List, Optional, Tuple

from . import protocol as P

BeaconCallback = Callable[[P.Beacon, int, float], None]       # beacon, rssi, wall time
BASE_UUID_TAIL = "-0000-1000-8000-00805f9b34fb"


def uuid_str(u) -> str:
    """Normalise a UUID: 16-bit ints/strings to the full form, lower case."""
    if isinstance(u, int):
        return f"{u:08x}{BASE_UUID_TAIL}"
    s = str(u).lower()
    if len(s) == 4:
        return f"0000{s}{BASE_UUID_TAIL}"
    return s


def uuid_from_le(b: bytes) -> str:
    """UUID bytes as they come over the air (little-endian, 2 or 16 bytes)."""
    if len(b) == 2:
        return uuid_str(f"{b[1]:02x}{b[0]:02x}")
    h = bytes(reversed(b)).hex()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def uuid_to_le(u: str) -> bytes:
    h = uuid_str(u).replace("-", "")
    return bytes(reversed(bytes.fromhex(h)))


class LinkError(Exception):
    """A GATT operation failed; `code` is the ATT/stack error when known."""

    def __init__(self, msg: str, code: Optional[int] = None):
        super().__init__(msg)
        self.code = code


class Link:
    """One connection to a tag."""
    address: str
    mtu: int = 23

    def has(self, uuid: str) -> bool:
        raise NotImplementedError

    async def read(self, uuid: str) -> bytes:
        raise NotImplementedError

    async def write(self, uuid: str, data: bytes, response: bool = True) -> None:
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError


class Transport:
    name = "?"
    description = ""

    async def start_scan(self, on_beacon: BeaconCallback) -> None:
        raise NotImplementedError

    async def stop_scan(self) -> None:
        raise NotImplementedError

    async def connect(self, address: str, timeout: float = 20.0) -> Link:
        raise NotImplementedError

    async def scan(self, seconds: float, on_beacon: Optional[BeaconCallback] = None) -> Dict[str, tuple]:
        """Collect beacons for `seconds`: {uid: (beacon, rssi, wall)} (latest)."""
        import asyncio
        seen: Dict[str, tuple] = {}

        def cb(b, rssi, wall):
            seen[b.uid] = (b, rssi, wall)
            if on_beacon:
                on_beacon(b, rssi, wall)
        await self.start_scan(cb)
        try:
            await asyncio.sleep(seconds)
        finally:
            await self.stop_scan()
        return seen

    async def find(self, addresses: List[str], seconds: float) -> Optional[str]:
        """Wait until any of `addresses` advertises (anything, not only a PRX
        beacon: also a tag in AppLoader mode). Default: via PRX beacons only."""
        want = {a.upper() for a in addresses}
        end = time.time() + seconds
        while time.time() < end:
            seen = await self.scan(3.0)
            for uid in seen:
                if uid.upper() in want:
                    return uid
        return None

    async def close(self) -> None:
        pass


# ---- selection ---------------------------------------------------------------------

_current: Optional[Transport] = None
_via = "ble"
OPTIONS: Dict[str, object] = {"legacy_local_time": False}


def configure(via: str) -> None:
    """Choose the transport for current(); it is created on first use."""
    global _via, _current
    _via, _current = via or "ble", None


def builtin() -> Dict[str, Tuple[str, str]]:
    return {"ble": ("proxtool.ble", "BleakTransport"), "ncp": ("proxtool.ncp", "NcpTransport")}


def available() -> Dict[str, object]:
    """name -> class or (module, class) for every transport that can be loaded."""
    out: Dict[str, object] = dict(builtin())
    try:
        from importlib.metadata import entry_points
        eps = entry_points()
        group = eps.select(group="proxtool.transports") if hasattr(eps, "select") else eps.get("proxtool.transports", [])
        for ep in group:
            out.setdefault(ep.name, ep)
    except Exception:
        pass
    return out


def parse_via(via: str) -> Tuple[str, Dict[str, str]]:
    """'ncp:COM5' -> ('ncp', {'port': 'COM5'}); 'ble' -> ('ble', {})."""
    name, _, opt = (via or "ble").partition(":")
    return name.strip().lower(), ({"port": opt} if opt else {})


def make(via: str = "ble") -> Transport:
    name, opts = parse_via(via)
    found = available().get(name)
    if found is None:
        raise SystemExit(f"unknown transport '{name}'; available: {', '.join(sorted(available()))}")
    if isinstance(found, tuple):
        import importlib
        cls = getattr(importlib.import_module(found[0]), found[1])
    else:
        cls = found.load()
    return cls(**opts)


def use(t: Transport) -> Transport:
    global _current
    _current = t
    return t


def current() -> Transport:
    global _current
    if _current is None:
        _current = make(_via)
    return _current
