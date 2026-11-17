# Copyright 2026 A.S.D - Alexander Schwartz Developments
# SPDX-License-Identifier: Apache-2.0
"""Talking to one ProxTit tag over any transport (see link.py).

    async with Tag(address) as t:          # the current transport (--via)
        await t.download(sink)

Firmware 02.00 and later speak the protocol in docs/ble-protocol.md. Tags still
on firmware 01.02.x (in the field, downloaded with the earlier NCP downloader)
are handled too, with what that firmware offers:

  - each read of the log returns one record and deletes it at once (no
    acknowledgement): proxtool stores every record before the next read, so at
    most the record in flight can be lost if the link drops;
  - the clock is set as a calendar date (SETTIME 0x0A); proxtool sends UTC, as
    for 02.00 (the earlier downloader sent the computer's local time: use
    `legacy_local_time=True` to keep that convention);
  - there are no sequence numbers (records get seq -1), no GETPAGE/GETSTATS.
"""
from __future__ import annotations

import datetime as dt
import re
import struct
import time
from typing import Callable, List, Optional, Tuple

from . import link as L
from . import protocol as P

LEGACY_SEQ = -1
LEGACY_MAX_READS = 5000                     # a 01.02.x tag holds at most a few hundred


def parse_version(s: str) -> Optional[Tuple[int, int, int]]:
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", s or "")
    return tuple(int(x) for x in m.groups()) if m else None


def is_legacy(fw: str) -> bool:
    v = parse_version(fw)
    return v is not None and v[0] < 2


def sdate_bytes(t: dt.datetime) -> bytes:
    """sdate_time_t: u8 year-1900, u8 month 0-11, u8 day, u8 h, u8 m, u8 s, u16 ms."""
    return struct.pack("<BBBBBBH", t.year - 1900, t.month - 1, t.day, t.hour, t.minute, t.second, 0)


def sdate_unix(b: bytes) -> int:
    y, mo, d, h, mi, s, _ = struct.unpack_from("<BBBBBBH", b, 0)
    return int(dt.datetime(1900 + y, mo + 1, max(d, 1), h, mi, s, tzinfo=dt.timezone.utc).timestamp())


def legacy_records(data: bytes) -> List[P.Record]:
    """A 01.02.x log read: one 16-byte record (01.02.28 and earlier) or a batch
    [u8 n][n x 16 B] (01.02.29/30). Anything else: nothing."""
    if len(data) == P.RECORD_LEN:
        return [P.parse_record(LEGACY_SEQ, data)]
    if len(data) >= 1 and len(data) == 1 + data[0] * P.RECORD_LEN:
        return [P.parse_record(LEGACY_SEQ, data[1 + i * P.RECORD_LEN:1 + (i + 1) * P.RECORD_LEN])
                for i in range(data[0])]
    return []


class Tag:
    """One connection to a tag through a transport."""

    def __init__(self, address: str, transport: Optional[L.Transport] = None, timeout: float = 20.0,
                 legacy_local_time: Optional[bool] = None):
        self.address = address
        self.transport = transport or L.current()
        self.timeout = timeout
        self.legacy_local_time = (bool(L.OPTIONS.get("legacy_local_time")) if legacy_local_time is None
                                  else legacy_local_time)
        self.link: Optional[L.Link] = None
        self._fw: Optional[str] = None

    async def __aenter__(self) -> "Tag":
        self.link = await self.transport.connect(self.address, self.timeout)
        return self

    async def __aexit__(self, *exc) -> None:
        if self.link is not None:
            await self.link.close()
            self.link = None

    # -- basics --
    async def command(self, cmd: int, payload: bytes = b"") -> bytes:
        await self.link.write(P.DATACP_UUID, P.cp(cmd, payload), response=True)
        return bytes(await self.link.read(P.DATACP_UUID))

    async def firmware(self) -> str:
        if self._fw is None:
            try:
                self._fw = bytes(await self.link.read(P.FW_REV_UUID)).decode(errors="replace").strip("\x00 ")
            except Exception:
                self._fw = "?"
        return self._fw

    async def legacy(self) -> bool:
        return is_legacy(await self.firmware())

    # -- clock --
    async def get_time(self) -> int:
        if await self.legacy():
            r = await self.command(P.CMD_GETTIME)
            if not P.reply_ok(r, P.CMD_GETTIME):
                raise RuntimeError("GETTIME refused")
            return sdate_unix(r[1:9])
        r = await self.command(P.CMD_GETPAGE)
        if not P.reply_ok(r, P.CMD_GETPAGE):
            raise RuntimeError("GETPAGE refused")
        return P.parse_getpage(r).time

    async def set_time(self, unix: Optional[int] = None) -> int:
        unix = int(time.time()) if unix is None else unix
        if await self.legacy():
            when = (dt.datetime.fromtimestamp(unix) if self.legacy_local_time
                    else dt.datetime.fromtimestamp(unix, dt.timezone.utc))
            r = await self.command(P.CMD_SETTIME, sdate_bytes(when))
            if not P.reply_ok(r, P.CMD_SETTIME):
                raise RuntimeError("SETTIME refused")
            return unix
        r = await self.command(P.CMD_SETTIME_UNIX, struct.pack("<I", unix))
        if not P.reply_ok(r, P.CMD_SETTIME_UNIX):
            raise RuntimeError("SETTIME refused")
        return struct.unpack_from("<I", r, 1)[0]

    # -- settings and state --
    async def get_cfg(self, reg: int) -> int:
        r = await self.command(P.CMD_GETCFG, struct.pack("<H", reg))
        if not P.reply_ok(r, P.CMD_GETCFG):
            raise RuntimeError(f"GETCFG 0x{reg:02X} refused")
        return P.reg_value(reg, struct.unpack_from("<H", r, 3)[0])

    async def set_cfg(self, reg: int, value: int) -> bool:
        r = await self.command(P.CMD_SETCFG, struct.pack("<HH", reg, value & 0xFFFF))
        return P.reply_ok(r, P.CMD_SETCFG)

    async def page(self) -> P.Page:
        if await self.legacy():
            # 01.02.x has no GETPAGE: no count, no sequence numbers; the clock is read.
            return P.Page(0, 0, 0, await self.get_time())
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
            try:
                info.config[P.REGS[reg]] = await self.get_cfg(reg)
            except RuntimeError:
                pass                        # older firmware: fewer registers
        info.page = await self.page()
        info.time = info.page.time
        if not await self.legacy():
            for pg in (0, 1):
                info.stats.update(await self.stats(pg))
        return info

    # -- download --
    async def download(self, sink: Callable[[List[P.Record]], None], ack: bool = True,
                       progress: Optional[Callable[[int, int], None]] = None, expected: int = 0) -> int:
        """Read the log batch by batch. Each batch goes to `sink` (which must store
        it) BEFORE the tag may delete it. Returns the number of records read.
        `expected` (e.g. the beacon's count) sizes the progress for 01.02.x tags."""
        if await self.legacy():
            return await self._download_legacy(sink, progress, expected)
        total = 0
        pending = (await self.page()).pending
        last_seq = None
        while True:
            data = bytes(await self.link.read(P.LOG_UUID))
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

    async def _download_legacy(self, sink, progress, expected: int) -> int:
        total = 0
        for _ in range(LEGACY_MAX_READS):
            try:
                data = bytes(await self.link.read(P.LOG_UUID))
            except L.LinkError:
                break                       # 01.02.28 answers an empty log with an ATT error
            recs = legacy_records(data)
            if not recs:
                break
            sink(recs)                      # the tag has already deleted them: store first
            total += len(recs)
            if progress:
                progress(total, max(expected, total))
        return total

    async def release(self, width_ms: int) -> bool:
        r = await self.command(P.CMD_RELEASE, struct.pack("<H", width_ms))
        return P.reply_ok(r, P.CMD_RELEASE)
