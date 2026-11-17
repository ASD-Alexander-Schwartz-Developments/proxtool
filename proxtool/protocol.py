"""ProxTit BLE wire format (firmware 02.00.x): beacon, control point, log records.

Normative description: Proxtit/docs/ble_download_protocol.md. Everything here is
plain bytes in / Python values out, so it can be tested without a radio.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import List, Optional

SERVICE_UUID = "01e59576-be13-47da-9c29-354a565cc874"
DATACP_UUID = "8093f8a5-82ce-4fac-9fb3-f7dab64c0b74"
LOG_UUID = "1d316924-9f39-47a3-a16d-a39846473eac"
FW_REV_UUID = "00002a26-0000-1000-8000-00805f9b34fb"

COMPANY_ID = 0x02FF            # bytes FF 02 in the beacon
COMPANY_ID_LEGACY = 0xFFFF
TAG_NAME = "PRX"
SIM_NAME = "PRS"

# Control-point commands (write prx_datacp, then read it back for the reply).
CMD_RELEASE = 0x08
CMD_GETTIME = 0x09
CMD_SETTIME = 0x0A
CMD_SETCFG = 0x10
CMD_GETCFG = 0x11
CMD_GETPAGE = 0x12
CMD_LOGACK = 0x13
CMD_GETSTATS = 0x14
CMD_SETTIME_UNIX = 0x15
CP_LEN = 28                     # u8 cmd + u8 data[27]

# Config registers (u16 each), README "Config registers".
REGS = {
    0x00: "prox_mode",
    0x01: "beacon_interval_ms",
    0x02: "beacon_duration_x100ms",
    0x03: "tx_power_ddbm",
    0x04: "scan_interval_ms",
    0x05: "proximity_threshold_db",
    0x06: "max_encounter_s",
    0x07: "scan_window_ms",
    0x08: "turn_on",
    0x09: "turn_off",
    0x0A: "silence_gap_s",
    0x0B: "rssi_split_db",
}
SIGNED_REGS = {0x03}

# Written by `proxtool bench start`: logger mode, the firmware's default radio
# schedule (a tag keeps old values in flash; the simulator plays the defaults)
# and the encounter rules the scenario expectations assume. Keep the radio
# values equal to PROX_*_DEFAULT* in Proxtit/proxtit_types.h.
DEFAULT_BENCH_CONFIG = {
    0x00: 1,        # prox_mode: logger
    0x01: 100,      # beacon interval (ms)
    0x02: 1,        # beacon duration x100 ms (>= interval: continuous)
    0x04: 1000,     # scan interval (ms)
    0x07: 35,       # scan window (ms)
    0x05: 85,       # proximity threshold (dB path loss)
    0x06: 900,      # maximum encounter length (s)
    0x0A: 30,       # silence gap (s)
    0x0B: 0,        # no RSSI split
}
REG_BY_NAME = {v: k for k, v in REGS.items()}

MODES = {0: "off", 1: "logger", 2: "modem"}

FLAG_TIME_SET = 0x01
FLAG_LOG_NEAR_FULL = 0x02
FLAG_LOW_BATTERY = 0x04

# Marker records: peer FF:FF:FF:FF:FF:<type>, rssi 127.
MARKER_RSSI = 127
MARKERS = {1: "BOOT", 2: "TIMESET", 3: "POWEROFF", 4: "START", 0xFE: "UNREADABLE"}
POWEROFF_REASONS = {1: "mode Off", 2: "low battery", 3: "host sleep"}

# EFR32BG22 EMU->RSTCAUSE bits (BOOT marker, GETSTATS reset_cause).
RESET_CAUSES = {0: "power-on", 1: "pin", 2: "EM4 wake", 3: "watchdog", 5: "lockup",
                6: "software", 7: "DVDD brown-out", 8: "DVDD-LE brown-out", 9: "DEC brown-out",
                10: "AVDD brown-out", 11: "IOVDD brown-out", 16: "DCI", 31: "VREGIN"}


def reset_cause_text(v: int) -> str:
    names = [n for bit, n in RESET_CAUSES.items() if v & (1 << bit)]
    return ",".join(names) if names else f"0x{v:X}"


RECORD_LEN = 16
LOG_HDR_LEN = 5


def uid_str(addr6: bytes) -> str:
    """bd_addr bytes (little-endian, addr[0] = LSB) -> 'AA:BB:CC:DD:EE:FF'."""
    return ":".join(f"{b:02X}" for b in reversed(addr6))


def uid_bytes(s: str) -> bytes:
    """'AA:BB:CC:DD:EE:FF' -> bd_addr bytes (addr[0] = LSB)."""
    parts = s.replace("-", ":").split(":")
    if len(parts) != 6:
        raise ValueError(f"bad address {s!r}")
    return bytes(int(p, 16) for p in reversed(parts))


# ---- beacon ----------------------------------------------------------------

@dataclass
class Beacon:
    name: str                   # "PRX" tag, "PRS" peer simulator status
    uid: str
    tx_power: int               # dBm the sender claims
    battery_pct: int
    time: int                   # tag clock (unix s); "PRS": simulator uptime (s)
    mode: int
    flags: int
    count: int                  # records waiting for download; scenario period for "PRS"
    # "PRS" v2 also: battery_pct = simulator boot count (low 8 bits),
    # tx_power = share of adverts the simulator sent late (%).

    @property
    def is_sim(self) -> bool:
        return self.name == SIM_NAME

    def flag_text(self) -> str:
        out = []
        if self.flags & FLAG_TIME_SET:
            out.append("clock-set")
        else:
            out.append("CLOCK-NOT-SET")
        if self.flags & FLAG_LOG_NEAR_FULL:
            out.append("LOG-NEAR-FULL")
        if self.flags & FLAG_LOW_BATTERY:
            out.append("LOW-BATTERY")
        return ",".join(out)


def parse_beacon(manufacturer_data: dict, local_name: Optional[str]) -> Optional[Beacon]:
    """Decode a PRX/PRS beacon from bleak's AdvertisementData fields."""
    if local_name not in (TAG_NAME, SIM_NAME):
        return None
    payload = manufacturer_data.get(COMPANY_ID) or manufacturer_data.get(COMPANY_ID_LEGACY)
    if payload is None or len(payload) < 18:
        return None
    tx, bat, sdt = struct.unpack_from("<bBI", payload, 0)
    uid = payload[6:12]
    mode, flags, count = struct.unpack_from("<BBI", payload, 12)
    return Beacon(local_name, uid_str(uid), tx, bat, sdt, mode, flags, count)


# ---- log records -------------------------------------------------------------

@dataclass
class Record:
    seq: int
    start: int                  # unix s (tag clock)
    duration: int               # s
    peer: str                   # peer UID; for markers FF:FF:FF:FF:FF:<type>
    rssi: int                   # mean dBm; 127 for markers
    tx_power: int               # dBm the peer advertised

    @property
    def marker(self) -> Optional[str]:
        if self.rssi == MARKER_RSSI and self.peer.startswith("FF:FF:FF:FF:FF:"):
            return MARKERS.get(int(self.peer[-2:], 16), "MARKER")
        return None

    def describe(self) -> str:
        m = self.marker
        if m is None:
            return f"encounter {self.peer} {self.duration}s rssi {self.rssi} tx {self.tx_power}"
        if m == "BOOT":
            return f"BOOT ({reset_cause_text(self.duration)}) boot-count(low) {self.tx_power & 0x7F}"
        if m == "TIMESET":
            return f"TIMESET old clock {self.duration} (step {self.start - self.duration:+d} s)"
        if m == "POWEROFF":
            return f"POWEROFF {POWEROFF_REASONS.get(self.duration, self.duration)}"
        if m == "START":
            return f"START logging (was {MODES.get(self.duration, self.duration)}, clock set: {bool(self.tx_power)})"
        return m


def parse_record(seq: int, b: bytes) -> Record:
    start, dur = struct.unpack_from("<II", b, 0)
    peer = b[8:14]
    rssi, tx = struct.unpack_from("<bb", b, 14)
    return Record(seq, start, dur, uid_str(peer), rssi, tx)


def parse_log_read(data: bytes) -> tuple[int, List[Record]]:
    """prx_log read -> (first_seq, records). [u8 n][u32 first_seq][n x 16 B]."""
    if len(data) < LOG_HDR_LEN:
        return 0, []
    n = data[0]
    first = struct.unpack_from("<I", data, 1)[0]
    if len(data) < LOG_HDR_LEN + n * RECORD_LEN:
        raise ValueError(f"short prx_log read: {len(data)} bytes for {n} records")
    recs = [parse_record(first + i, data[LOG_HDR_LEN + i * RECORD_LEN: LOG_HDR_LEN + (i + 1) * RECORD_LEN])
            for i in range(n)]
    return first, recs


# ---- control point -----------------------------------------------------------

def cp(cmd: int, payload: bytes = b"") -> bytes:
    if len(payload) > CP_LEN - 1:
        raise ValueError("payload too long")
    return bytes([cmd]) + payload + bytes(CP_LEN - 1 - len(payload))


def reply_ok(reply: bytes, cmd: int) -> bool:
    return len(reply) >= 1 and reply[0] == (cmd | 0x80)


@dataclass
class Page:
    pending: int
    head_seq: int
    overwritten: int
    time: int


def parse_getpage(reply: bytes) -> Page:
    return Page(*struct.unpack_from("<IIII", reply, 1))


def parse_logack(reply: bytes) -> tuple[int, int, int]:
    removed, pending, head = struct.unpack_from("<HII", reply, 1)
    return removed, pending, head


STATS_FIELDS = {
    0: ("<IIIHHIIBB", ["uptime_s", "boot_count", "reset_cause", "vbat_mv", "vbat_min_mv",
                        "nvm_errors", "log_overwritten", "open_encounters", "flags"]),
    1: ("<IIIIIIH", ["beacons", "far", "opened", "logged", "dropped_full", "split_max", "split_rssi"]),
    2: ("<IIIB", ["time", "log_count", "head_seq", "mode"]),
}


def parse_stats(reply: bytes) -> dict:
    page = reply[1]
    fmt, names = STATS_FIELDS[page]
    vals = struct.unpack_from(fmt, reply, 2)
    return dict(zip(names, vals))


def reg_value(reg: int, raw: int) -> int:
    if reg in SIGNED_REGS and raw >= 0x8000:
        return raw - 0x10000
    return raw


@dataclass
class TagInfo:
    address: str
    firmware: str = ""
    time: int = 0
    config: dict = field(default_factory=dict)
    page: Optional[Page] = None
    stats: dict = field(default_factory=dict)
