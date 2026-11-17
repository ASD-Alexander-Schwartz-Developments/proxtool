# Copyright 2026 A.S.D - Alexander Schwartz Developments
# SPDX-License-Identifier: Apache-2.0
"""Firmware update over Bluetooth (Silicon Labs AppLoader OTA DFU).

The tag firmware contains the Silicon Labs "in-place OTA DFU" component and the
AppLoader bootloader stage (Proxtit/ProxTit.slcp). An update is:

  1. Connect to the running tag and write 0x00 to OTA Control. The tag
     closes the link and restarts in AppLoader (DFU) mode.
  2. Connect to the AppLoader (same address, or the address + 1 if the
     AppLoader is configured that way), write 0x00 to OTA Control, then the
     .gbl file in chunks to OTA Data, then 0x03 to OTA Control.
  3. The tag restarts into the new firmware. Its settings and its log live in
     NVM3, outside the application area, and are kept.

If the transfer is interrupted, the tag stays in AppLoader mode (it has no valid
application) and the update can simply be run again.

Pure helpers (file checks, chunking, addresses) are unit-tested; the radio part
needs a tag.
"""
from __future__ import annotations

import asyncio
import re
import struct
from dataclasses import dataclass
from typing import Callable, List, Optional

OTA_SERVICE = "1d14d6ee-fd63-4fa1-bfa4-8f47b42119f0"
OTA_CONTROL = "f7bf3564-fb6d-4e53-88a4-5e37e0326063"
OTA_DATA = "984227f3-34fc-4045-a5d0-2c581f81a153"
APPLOADER_VERSION = "4f4a2368-8cca-451e-bfff-cf0e2ee23e9f"

CTRL_START = b"\x00"
CTRL_END = b"\x03"

GBL_HEADER_TAG = 0x03A617EB                 # first 4 bytes of every .gbl, little-endian
GBL_APP_TAG = 0xF40A0AF4                    # application properties tag
VERSION_RE = re.compile(rb"(?<![0-9])([0-9]{2}\.[0-9]{2}\.[0-9]{2})(?![0-9])")


@dataclass
class GblInfo:
    size: int
    version: Optional[str]                  # ProxTit version string found in the image, if any
    has_app: bool


def check_gbl(data: bytes) -> GblInfo:
    """Raise ValueError unless `data` looks like a GBL update file; report what
    it contains."""
    if len(data) < 64:
        raise ValueError("file too small to be a firmware update")
    if struct.unpack_from("<I", data, 0)[0] != GBL_HEADER_TAG:
        raise ValueError("not a .gbl firmware update file (wrong header)")
    has_app = struct.pack("<I", GBL_APP_TAG) in data
    if not has_app:
        raise ValueError("the .gbl file holds no application")
    found = [v.decode() for v in VERSION_RE.findall(data) if v != b"00.00.00"]
    version = found[0] if found else None
    return GblInfo(len(data), version, has_app)


def chunk_size(mtu: int) -> int:
    """Largest write that fits the link (ATT MTU - 3), a multiple of 4, at most 244."""
    n = min(244, max(20, mtu - 3))
    return n - n % 4


def chunks(data: bytes, size: int) -> List[bytes]:
    return [data[i:i + size] for i in range(0, len(data), size)]


def address_plus_one(address: str) -> str:
    """AA:BB:CC:DD:EE:FF + 1 (the AppLoader can be configured to use it)."""
    v = int(address.replace(":", ""), 16) + 1
    h = f"{v & 0xFFFFFFFFFFFF:012X}"
    return ":".join(h[i:i + 2] for i in range(0, 12, 2))


# ---- radio (any transport, see link.py) ----------------------------------------------

Progress = Callable[[str, float], None]     # (stage text, 0..1)


async def update(address: str, gbl: bytes, progress: Progress, transport=None) -> str:
    """Update the tag at `address` with the .gbl image through `transport`
    (default: the current one). Returns the firmware version the tag reports
    afterwards."""
    from . import link as L
    from .tag import Tag
    check_gbl(gbl)
    t = transport or L.current()

    # 1. Running firmware -> AppLoader.
    progress("Connecting to the tag", 0.0)
    link = await t.connect(address)
    try:
        in_dfu = link.has(OTA_DATA)
        if not in_dfu:
            if not link.has(OTA_CONTROL):
                raise RuntimeError("this tag's firmware has no update service")
            progress("Restarting the tag in update mode", 0.02)
            await link.write(OTA_CONTROL, CTRL_START, response=True)
    finally:
        await link.close()

    # 2. Find and connect to the AppLoader.
    if not in_dfu:
        await asyncio.sleep(2.0)
    progress("Waiting for the tag in update mode", 0.04)
    dfu_addr = await t.find([address, address_plus_one(address)], 30.0)
    if dfu_addr is None:
        raise RuntimeError("the tag did not come back in update mode (move closer and try again)")
    link = await t.connect(dfu_addr)
    try:
        if not link.has(OTA_DATA):
            raise RuntimeError("connected, but the update service is missing (not in update mode?)")
        await link.write(OTA_CONTROL, CTRL_START, response=True)
        parts = chunks(gbl, chunk_size(link.mtu))
        for i, part in enumerate(parts):
            await link.write(OTA_DATA, part, response=True)
            if i % 8 == 0 or i == len(parts) - 1:
                progress(f"Sending firmware ({(i + 1) * 100 // len(parts)} %)", 0.05 + 0.9 * (i + 1) / len(parts))
        progress("Finishing", 0.96)
        await link.write(OTA_CONTROL, CTRL_END, response=True)
    finally:
        await link.close()

    # 3. The tag restarts into the new firmware: read its version back.
    progress("Waiting for the tag to restart", 0.97)
    await asyncio.sleep(3.0)
    if await t.find([address], 30.0) is None:
        raise RuntimeError("update sent, but the tag was not heard afterwards; check it with Details")
    async with Tag(address, t) as tag:
        fw = await tag.firmware()
    progress("Done", 1.0)
    return fw
