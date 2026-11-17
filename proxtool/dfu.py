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
import time
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


# ---- radio ------------------------------------------------------------------------

Progress = Callable[[str, float], None]     # (stage text, 0..1)


async def _connect(address: str, timeout: float = 20.0):
    from bleak import BleakClient
    # Do not reuse the GATT table cached by Windows: the AppLoader exposes a
    # different one at the same address.
    client = BleakClient(address, timeout=timeout, winrt={"use_cached_services": False})
    await client.connect()
    return client


async def _find(addresses: List[str], seconds: float) -> Optional[str]:
    from bleak import BleakScanner
    want = {a.upper() for a in addresses}
    end = time.time() + seconds
    while time.time() < end:
        devs = await BleakScanner.discover(timeout=3.0)
        for d in devs:
            if d.address.upper() in want:
                return d.address
        await asyncio.sleep(0.2)
    return None


def _has(client, uuid: str) -> bool:
    try:
        return client.services.get_characteristic(uuid) is not None
    except Exception:
        return False


async def update(address: str, gbl: bytes, progress: Progress) -> str:
    """Update the tag at `address` with the .gbl image. Returns the firmware
    version the tag reports afterwards."""
    check_gbl(gbl)

    # 1. Running firmware -> AppLoader.
    progress("Connecting to the tag", 0.0)
    client = await _connect(address)
    try:
        in_dfu = _has(client, OTA_DATA)
        if not in_dfu:
            if not _has(client, OTA_CONTROL):
                raise RuntimeError("this tag's firmware has no update service")
            progress("Restarting the tag in update mode", 0.02)
            await client.write_gatt_char(OTA_CONTROL, CTRL_START, response=True)
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass

    # 2. Find and connect to the AppLoader.
    if not in_dfu:
        await asyncio.sleep(2.0)
    progress("Waiting for the tag in update mode", 0.04)
    dfu_addr = await _find([address, address_plus_one(address)], 30.0)
    if dfu_addr is None:
        raise RuntimeError("the tag did not come back in update mode (move closer and try again)")
    client = await _connect(dfu_addr)
    try:
        if not _has(client, OTA_DATA):
            raise RuntimeError("connected, but the update service is missing (not in update mode?)")
        await client.write_gatt_char(OTA_CONTROL, CTRL_START, response=True)
        size = chunk_size(getattr(client, "mtu_size", 23))
        parts = chunks(gbl, size)
        for i, part in enumerate(parts):
            await client.write_gatt_char(OTA_DATA, part, response=True)
            if i % 8 == 0 or i == len(parts) - 1:
                progress(f"Sending firmware ({(i + 1) * 100 // len(parts)} %)", 0.05 + 0.9 * (i + 1) / len(parts))
        progress("Finishing", 0.96)
        await client.write_gatt_char(OTA_CONTROL, CTRL_END, response=True)
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass

    # 3. The tag restarts into the new firmware: read its version back.
    progress("Waiting for the tag to restart", 0.97)
    await asyncio.sleep(3.0)
    if await _find([address], 30.0) is None:
        raise RuntimeError("update sent, but the tag was not heard afterwards; check it with Details")
    from . import ble
    async with ble.Tag(address) as t:
        fw = await t.firmware()
    progress("Done", 1.0)
    return fw
