# Copyright 2026 A.S.D - Alexander Schwartz Developments
# SPDX-License-Identifier: Apache-2.0
"""Transport "ncp": a USB Bluetooth adapter running the Silicon Labs Bluetooth
stack as a network co-processor (NCP), e.g. a Thunderboard BG22 with the
"Bluetooth - NCP" firmware, driven over its serial port with pyBGAPI.

This is how ProxTit tags were downloaded before proxtool (the earlier
"proxtit-downloader-py" scripts, an NCP host). It needs no Bluetooth on the
computer, works the same on Windows and Linux, and the adapter can sit where
the tags are (a USB extension cable).

    proxtool --via ncp scan                 # adapter found automatically
    proxtool --via ncp:COM7 download ...    # or name the serial port

Needs `pip install pybgapi` (Silicon Labs, zlib licence). BGAPI renumbers
commands and events between major stack versions (e.g. 11.x moved GATT write and
characteristic-value), so proxtool ships one definition per major version, from
Silicon Labs' zlib-licensed pybgapi-examples (api/sl_bt-<version>.xapi), asks the
adapter which stack it runs and uses the matching one. PROXTOOL_XAPI names a
definition file to use instead.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Callable, Dict, List, Optional

from . import link as L
from . import protocol as P

log = logging.getLogger("proxtool.ncp")

API_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "api")
XAPIS = {9: os.path.join(API_DIR, "sl_bt-9.0.0.xapi"),       # Simplicity SDK 2024.12 (stack 9.x)
         11: os.path.join(API_DIR, "sl_bt-11.0.1.xapi")}     # Simplicity SDK 2025.12 (stack 11.x)
XAPI_OVERRIDE = os.environ.get("PROXTOOL_XAPI")


def xapi_for(major: int) -> str:
    """The bundled definition for a stack major version: the newest one not newer."""
    fit = [m for m in XAPIS if m <= major]
    return XAPIS[max(fit)] if fit else XAPIS[min(XAPIS)]


def _tolerate_unknown_events(bgapi) -> None:
    """pyBGAPI's reader thread stops on an event its definition does not know
    (e.g. a newer stack's), and the adapter then goes silent. Replace its loop
    with one that skips such a message.

    ALTERED copy of BGApiConnHandler.run from pyBGAPI 1.3 (Copyright Silicon
    Laboratories Inc., zlib licence): the only change is the try/except around
    deser.parse. Marked as altered as the zlib licence requires."""
    from bgapi import bglib, serdeser
    if getattr(bglib.BGApiConnHandler, "_proxtool_tolerant", False):
        return

    def run(self):
        self.conn.set_read_timeout(self.READ_TIMEOUT)
        self.conn.set_write_timeout(self.WRITE_TIMEOUT)
        while not self.stop_flag.is_set():
            header_start = self.read(size=1)
            if header_start is None:
                continue
            device_id = (header_start[0] & 0x78) >> 3
            if device_id not in self.ser.apis.keys():
                continue
            header_rest = self.read(size=serdeser.HEADER_LENGTH - 1)
            if header_rest is None:
                continue
            header = header_start + header_rest
            cmdevt, device_id, payload_len, class_index, command_index = self.deser.parseHeader(header)
            payload = self.read(size=payload_len)
            if payload is None:
                continue
            try:                                            # proxtool change
                (apicmdevt, headers, params) = self.deser.parse(header, payload, fromHost=False)
            except serdeser.DeserializerError as e:
                log.debug("skipped a BGAPI message the definition does not know: %s", e)
                continue
            if cmdevt == serdeser.MSG_COMMAND:
                if self.waiting_response.is_set():
                    self.response_queue.put((apicmdevt, headers, params))
                else:
                    log.debug("late response %s", bglib.BGResponse(apicmdevt, params))
            else:
                self.event_handler(bglib.BGEvent(apicmdevt, params))

    bglib.BGApiConnHandler.run = run
    bglib.BGApiConnHandler._proxtool_tolerant = True
USB_VIDS = {0x1366: "SEGGER J-Link (Thunderboard, WSTK)", 0x10C4: "Silicon Labs CP210x"}
PROC_TIMEOUT_S = 10.0
DISCOVER_OBSERVATION = 2                    # report every advertiser, connectable or not
PHY_1M = 1


def candidate_ports() -> List[tuple]:
    """(port, description) of serial ports that look like a Silicon Labs adapter."""
    try:
        import serial.tools.list_ports
    except ImportError:
        return []
    return [(p.device, USB_VIDS[p.vid]) for p in serial.tools.list_ports.comports() if p.vid in USB_VIDS]


def parse_ad(data: bytes) -> tuple:
    """Raw advertising data -> (local name or None, {company_id: payload})."""
    name, mfr = None, {}
    i = 0
    while i < len(data):
        n = data[i]
        if n == 0 or i + 1 + n > len(data):
            break
        typ, val = data[i + 1], data[i + 2:i + 1 + n]
        if typ in (0x08, 0x09):
            name = val.decode("utf-8", errors="replace")
        elif typ == 0xFF and len(val) >= 2:
            mfr[val[0] | (val[1] << 8)] = bytes(val[2:])
        i += 1 + n
    return name, mfr


class _Proc:
    """One GATT procedure in flight: collect events, finish on procedure_completed."""

    def __init__(self, loop, collect: Optional[str]):
        self.collect = collect
        self.items: list = []
        self.done = loop.create_future()


class NcpLink(L.Link):
    def __init__(self, t: "NcpTransport", conn: int, address: str):
        self.t, self.conn, self.address = t, conn, address
        self.mtu = 23
        self.chars: Dict[str, int] = {}
        self.proc: Optional[_Proc] = None
        self.closed = t.loop.create_future()

    def on_event(self, evt) -> None:
        if evt == "bt_evt_gatt_mtu_exchanged":
            self.mtu = evt.mtu
        elif evt == "bt_evt_connection_closed":
            if not self.closed.done():
                self.closed.set_result(evt.reason)
            if self.proc and not self.proc.done.done():
                self.proc.done.set_exception(L.LinkError(f"connection closed (reason {evt.reason:#x})", evt.reason))
        elif self.proc is not None:
            if evt == "bt_evt_gatt_procedure_completed":
                if not self.proc.done.done():
                    self.proc.done.set_result(evt.result)
            elif self.proc.collect and evt == self.proc.collect:
                self.proc.items.append(evt)

    async def _run(self, start: Callable[[], object], collect: Optional[str] = None) -> list:
        if self.closed.done():
            raise L.LinkError("not connected")
        self.proc = _Proc(self.t.loop, collect)
        try:
            self.t.call(start)
            result = await asyncio.wait_for(self.proc.done, PROC_TIMEOUT_S)
        except asyncio.TimeoutError:
            raise L.LinkError("GATT procedure timed out")
        finally:
            items, self.proc = self.proc.items if self.proc else [], None
        if result != 0:
            raise L.LinkError(f"GATT error {result:#06x}", result)
        return items

    async def discover(self) -> None:
        gatt = self.t.lib.bt.gatt
        services = await self._run(lambda: gatt.discover_primary_services(self.conn), "bt_evt_gatt_service")
        for s in services:
            chars = await self._run(lambda: gatt.discover_characteristics(self.conn, s.service),
                                    "bt_evt_gatt_characteristic")
            for c in chars:
                self.chars[L.uuid_from_le(bytes(c.uuid))] = c.characteristic

    def _handle(self, uuid: str) -> int:
        h = self.chars.get(L.uuid_str(uuid))
        if h is None:
            raise L.LinkError(f"characteristic {uuid} not found on {self.address}")
        return h

    def has(self, uuid: str) -> bool:
        return L.uuid_str(uuid) in self.chars

    async def read(self, uuid: str) -> bytes:
        h = self._handle(uuid)
        vals = await self._run(lambda: self.t.lib.bt.gatt.read_characteristic_value(self.conn, h),
                               "bt_evt_gatt_characteristic_value")
        out = bytearray()
        for v in sorted(vals, key=lambda v: v.offset):
            out[v.offset:v.offset + len(v.value)] = bytes(v.value)
        return bytes(out)

    async def write(self, uuid: str, data: bytes, response: bool = True) -> None:
        h = self._handle(uuid)
        gatt = self.t.lib.bt.gatt
        if response:
            await self._run(lambda: gatt.write_characteristic_value(self.conn, h, data))
        else:
            self.t.call(lambda: gatt.write_characteristic_value_without_response(self.conn, h, data))

    async def close(self) -> None:
        if self.closed.done():
            return
        try:
            self.t.call(lambda: self.t.lib.bt.connection.close(self.conn))
            await asyncio.wait_for(asyncio.shield(self.closed), 5.0)
        except Exception:
            pass
        finally:
            self.t.links.pop(self.conn, None)


class NcpTransport(L.Transport):
    name = "ncp"
    description = "USB Bluetooth adapter (Silicon Labs NCP)"

    def __init__(self, port: Optional[str] = None, baudrate: int = 115200, rtscts: bool = False,
                 lib=None, **_opts):
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.links: Dict[int, NcpLink] = {}
        self.addr_types: Dict[str, int] = {}
        self.heard: Dict[str, float] = {}           # any advertiser: address -> wall time
        self._beacon_cb: Optional[L.BeaconCallback] = None
        self._scanning = False
        self._waiters: List[tuple] = []
        self.stack_version = ""
        if lib is not None:                         # tests: a stand-in for pyBGAPI
            self.port, self.lib, self.bgapi = "test", lib, None
            lib.event_handler = self._from_reader
            return
        try:
            import bgapi
        except ImportError:
            raise SystemExit("the NCP adapter needs pyBGAPI: pip install pybgapi")
        if not port:
            found = candidate_ports()
            if not found:
                raise SystemExit("no NCP adapter found: plug it in, or name the port (--via ncp:COM7)")
            if len(found) > 1:
                raise SystemExit("several possible adapters: name one with --via ncp:PORT ("
                                 + ", ".join(f"{p} = {d}" for p, d in found) + ")")
            port = found[0][0]
        self.port = port
        self.bgapi = bgapi
        _tolerate_unknown_events(bgapi)
        self.baudrate, self.rtscts = int(baudrate), rtscts
        self.xapi = XAPI_OVERRIDE or XAPIS[max(XAPIS)]
        self.lib = self._new_lib()

    def _new_lib(self):
        return self.bgapi.BGLib(self.bgapi.SerialConnector(self.port, baudrate=self.baudrate, rtscts=self.rtscts),
                                self.xapi, event_handler=self._from_reader)

    # -- plumbing --
    def call(self, fn: Callable[[], object]):
        """A BGAPI command (blocks for its response, a few ms)."""
        failed = self.bgapi.bglib.CommandFailedError if self.bgapi else RuntimeError
        try:
            return fn()
        except failed as e:
            raise L.LinkError(f"adapter refused: {e}", getattr(e, "errorcode", None)) from e

    def _from_reader(self, evt) -> None:            # pyBGAPI's reader thread
        loop = self.loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self._dispatch, evt)

    def _dispatch(self, evt) -> None:
        if evt == "bt_evt_scanner_legacy_advertisement_report":
            addr = str(evt.address).upper()
            self.heard[addr] = time.time()
            self.addr_types[addr] = evt.address_type
            if self._beacon_cb is not None:
                name, mfr = parse_ad(bytes(evt.data))
                b = P.parse_beacon(mfr, name)
                if b is not None:
                    self._beacon_cb(b, evt.rssi, time.time())
        conn = getattr(evt, "connection", None)
        if conn is not None and conn in self.links:
            self.links[conn].on_event(evt)
        for w in list(self._waiters):
            pred, fut = w
            if not fut.done() and pred(evt):
                fut.set_result(evt)
                self._waiters.remove(w)

    def _expect(self, pred) -> asyncio.Future:
        fut = self.loop.create_future()
        self._waiters.append((pred, fut))
        return fut

    async def _ensure(self) -> None:
        running = asyncio.get_running_loop()
        if self.loop is not None:
            if self.loop is not running:
                # The command line runs one event loop per step (asyncio.run):
                # the adapter stays open, events now go to the new loop.
                self.loop = running
                self._waiters.clear()
                self.links.clear()
            return
        self.loop = running
        evt = None
        if self.bgapi is None:                      # tests: the stand-in adapter
            evt = await self._boot()
        else:
            # Try each definition (newest first: its reboot works on every stack
            # that has one) and both hardware flow control settings (the Silicon
            # Labs example enables RTS/CTS; many adapters do not wire it).
            for xapi in ([XAPI_OVERRIDE] if XAPI_OVERRIDE else [XAPIS[m] for m in sorted(XAPIS, reverse=True)]):
                for rtscts in (self.rtscts, not self.rtscts):
                    self.xapi, self.rtscts = xapi, rtscts
                    self.lib = self._new_lib()
                    evt = await self._boot()
                    if evt is not None:
                        break
                if evt is not None:
                    break
            if evt is not None and not XAPI_OVERRIDE and xapi_for(evt.major) != self.xapi:
                # Booted: now talk with the definition that matches its stack.
                self.lib.close()
                self.xapi = xapi_for(evt.major)
                self.lib = self._new_lib()
                self.lib.open()
        if evt is None:
            self.loop = None
            raise SystemExit(f"no answer from the NCP adapter on {self.port} (is it running the "
                             "Silicon Labs NCP firmware? is another program using the port?)")
        self.stack_version = f"{evt.major}.{evt.minor}.{evt.patch}"
        host = getattr(self.lib.bt, "__version__", "?")
        if self.stack_version != host:
            log.info("NCP stack %s, BGAPI definition %s", self.stack_version, host)
        self.call(lambda: self.lib.bt.gatt.set_max_mtu(247))

    async def _boot(self):
        """Open the port, reset the adapter, wait for its boot event (None if silent)."""
        try:
            self.lib.open()
        except Exception as e:
            raise SystemExit(f"cannot open {self.port}: {e}")
        boot = self._expect(lambda e: e == "bt_evt_system_boot")
        try:
            # system_reboot (newer stacks: system_reset answers "not supported");
            # system_reset for stacks that predate reboot.
            try:
                self.lib.bt.system.reboot()
            except Exception:
                self.lib.bt.system.reset(0)
            return await asyncio.wait_for(boot, 4.0)
        except Exception:                      # timeout, or the write blocked (flow control)
            boot.cancel()
            try:
                self.lib.close()
            except Exception:
                pass
            return None

    # -- Transport --
    async def start_scan(self, on_beacon: L.BeaconCallback) -> None:
        await self._ensure()
        self._beacon_cb = on_beacon
        if not self._scanning:
            self.call(lambda: self.lib.bt.scanner.start(PHY_1M, DISCOVER_OBSERVATION))
            self._scanning = True

    async def stop_scan(self) -> None:
        self._beacon_cb = None
        if self._scanning:
            self._scanning = False
            try:
                self.call(lambda: self.lib.bt.scanner.stop())
            except L.LinkError:
                pass

    async def connect(self, address: str, timeout: float = 20.0) -> L.Link:
        await self._ensure()
        addr = address.upper()
        atype = self.addr_types.get(addr, 0)
        opened = self._expect(lambda e: e == "bt_evt_connection_opened" and str(e.address).upper() == addr)
        rsp = self.call(lambda: self.lib.bt.connection.open(addr.lower(), atype, PHY_1M))
        conn = rsp.connection
        link = NcpLink(self, conn, addr)
        self.links[conn] = link
        try:
            await asyncio.wait_for(opened, timeout)
        except asyncio.TimeoutError:
            await link.close()
            raise L.LinkError(f"could not connect to {addr} (in range? awake?)")
        try:
            await link.discover()
        except Exception:
            await link.close()
            raise
        return link

    async def find(self, addresses, seconds: float) -> Optional[str]:
        await self._ensure()
        want = {a.upper() for a in addresses}
        t0 = time.time()
        was = self._scanning
        if not was:
            self.call(lambda: self.lib.bt.scanner.start(PHY_1M, DISCOVER_OBSERVATION))
            self._scanning = True
        try:
            while time.time() - t0 < seconds:
                for a in want:
                    if self.heard.get(a, 0) >= t0:
                        return a
                await asyncio.sleep(0.2)
            return None
        finally:
            if not was:
                await self.stop_scan()

    async def close(self) -> None:
        for link in list(self.links.values()):
            await link.close()
        await self.stop_scan()
        try:
            self.lib.close()
        except Exception:
            pass
        self.loop = None
