# Copyright 2026 A.S.D - Alexander Schwartz Developments
# SPDX-License-Identifier: Apache-2.0
"""BLE side of proxtool (bleak). Scan for beacons, and talk to one tag."""
from __future__ import annotations

import asyncio
import struct
import time
from typing import Callable, Dict, List, Optional

from . import protocol as P

try:
    from bleak import BleakClient, BleakScanner
except ImportError:  # pragma: no cover - tests run without bleak
    BleakClient = BleakScanner = None


def _need_bleak() -> None:
    if BleakScanner is None:
        raise SystemExit("proxtool needs bleak: pip install bleak")


async def scan(seconds: float, on_beacon: Optional[Callable[[P.Beacon, int, float], None]] = None
               ) -> Dict[str, tuple]:
    """Collect beacons for `seconds`. Returns {uid: (beacon, rssi, wall_time)} (latest)."""
    _need_bleak()
    seen: Dict[str, tuple] = {}

    def cb(device, adv):
        b = P.parse_beacon(adv.manufacturer_data, adv.local_name)
        if b is None:
            return
        now = time.time()
        seen[b.uid] = (b, adv.rssi, now)
        if on_beacon:
            on_beacon(b, adv.rssi, now)

    async with BleakScanner(cb):
        await asyncio.sleep(seconds)
    return seen


class Tag:
    """One connection to a tag. Use as `async with Tag(addr) as t:`."""

    def __init__(self, address: str, timeout: float = 20.0):
        _need_bleak()
        self.address = address
        # No cached GATT table: a firmware update can change it (Windows caches it per address).
        self.client = BleakClient(address, timeout=timeout, winrt={"use_cached_services": False})

    async def __aenter__(self) -> "Tag":
        await self.client.connect()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.client.disconnect()

    async def command(self, cmd: int, payload: bytes = b"") -> bytes:
        await self.client.write_gatt_char(P.DATACP_UUID, P.cp(cmd, payload), response=True)
        return bytes(await self.client.read_gatt_char(P.DATACP_UUID))

    async def firmware(self) -> str:
        try:
            return bytes(await self.client.read_gatt_char(P.FW_REV_UUID)).decode(errors="replace")
        except Exception:
            return "?"

    async def get_time(self) -> int:
        r = await self.command(P.CMD_GETPAGE)
        if not P.reply_ok(r, P.CMD_GETPAGE):
            raise RuntimeError("GETPAGE refused")
        return P.parse_getpage(r).time

    async def set_time(self, unix: Optional[int] = None) -> int:
        unix = int(time.time()) if unix is None else unix
        r = await self.command(P.CMD_SETTIME_UNIX, struct.pack("<I", unix))
        if not P.reply_ok(r, P.CMD_SETTIME_UNIX):
            raise RuntimeError("SETTIME refused (firmware older than 02.00?)")
        return struct.unpack_from("<I", r, 1)[0]

    async def get_cfg(self, reg: int) -> int:
        r = await self.command(P.CMD_GETCFG, struct.pack("<H", reg))
        if not P.reply_ok(r, P.CMD_GETCFG):
            raise RuntimeError(f"GETCFG 0x{reg:02X} refused")
        return P.reg_value(reg, struct.unpack_from("<H", r, 3)[0])

    async def set_cfg(self, reg: int, value: int) -> bool:
        r = await self.command(P.CMD_SETCFG, struct.pack("<HH", reg, value & 0xFFFF))
        return P.reply_ok(r, P.CMD_SETCFG)

    async def page(self) -> P.Page:
        r = await self.command(P.CMD_GETPAGE)
        if not P.reply_ok(r, P.CMD_GETPAGE):
            raise RuntimeError("GETPAGE refused")
        return P.parse_getpage(r)

    async def stats(self, page: int) -> dict:
        r = await self.command(P.CMD_GETSTATS, bytes([page]))
        if not P.reply_ok(r, P.CMD_GETSTATS):
            raise RuntimeError(f"GETSTATS {page} refused")
        return P.parse_stats(r)

    async def info(self) -> P.TagInfo:
        info = P.TagInfo(self.address)
        info.firmware = await self.firmware()
        for reg in P.REGS:
            info.config[P.REGS[reg]] = await self.get_cfg(reg)
        info.page = await self.page()
        info.time = info.page.time
        for pg in (0, 1):
            info.stats.update(await self.stats(pg))
        return info

    async def download(self, sink: Callable[[List[P.Record]], None], ack: bool = True,
                       progress: Optional[Callable[[int, int], None]] = None) -> int:
        """Read the log batch by batch. Each batch goes to `sink` (which must store
        it) BEFORE it is acknowledged, so a dropped link never loses a record.
        Returns the number of records read."""
        total = 0
        pending = (await self.page()).pending
        last_seq = None
        while True:
            data = bytes(await self.client.read_gatt_char(P.LOG_UUID))
            first, recs = P.parse_log_read(data)
            if not recs:
                break
            if not ack and last_seq is not None and first == last_seq:
                break                       # without acks the tag serves the same batch
            last_seq = first
            sink(recs)
            total += len(recs)
            if progress:
                progress(total, pending)
            if not ack:
                break                       # read-only: one batch
            r = await self.command(P.CMD_LOGACK, struct.pack("<IH", first, len(recs)))
            if not P.reply_ok(r, P.CMD_LOGACK):
                raise RuntimeError("LOGACK refused")
        return total

    async def release(self, width_ms: int) -> bool:
        r = await self.command(P.CMD_RELEASE, struct.pack("<H", width_ms))
        return P.reply_ok(r, P.CMD_RELEASE)
