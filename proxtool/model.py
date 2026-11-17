# Copyright 2026 A.S.D - Alexander Schwartz Developments
# SPDX-License-Identifier: Apache-2.0
"""What the window shows, computed without Tk or a radio (unit-tested): the tag
table from the beacons heard, and the user's saved preferences."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, List, Tuple

from . import protocol as P

CLOCK_TOLERANCE_S = 5           # a beacon's clock can be ~1 s old; more than this is "off"
FORGET_AFTER_S = 120            # a tag not heard for this long leaves the table


@dataclass
class Row:
    uid: str
    mode: str
    records: int
    battery: str
    clock: str
    clock_ok: bool
    signal: str
    heard: str

    def values(self) -> Tuple[str, ...]:
        return (self.uid, self.mode, str(self.records), self.battery, self.clock, self.signal, self.heard)


COLUMNS = (("uid", "Tag", 150), ("mode", "Mode", 70), ("records", "Records", 70),
           ("battery", "Battery", 70), ("clock", "Clock", 150), ("signal", "Signal", 70),
           ("heard", "Last heard", 80))


def tag_rows(seen: Dict[str, tuple], now: float) -> List[Row]:
    """seen: {uid: (beacon, rssi, wall)} as bleak delivered them. Tags only (the
    bench simulator is left out), most recently heard first."""
    rows = []
    # The bench simulator's virtual peers carry its address with a different
    # last byte: leave them out with the simulator itself.
    sims = {uid[:-2] for uid, (b, _, _) in seen.items() if b.is_sim}
    for uid, (b, rssi, wall) in seen.items():
        if b.is_sim or uid[:-2] in sims or now - wall > FORGET_AFTER_S:
            continue
        if not b.flags & P.FLAG_TIME_SET:
            clock, ok = "NOT SET", False
        else:
            off = b.time - (wall)
            ok = abs(off) <= CLOCK_TOLERANCE_S
            clock = "ok" if ok else f"off by {off:+.0f} s"
        mode = P.MODES.get(b.mode, str(b.mode))
        if b.flags & P.FLAG_LOG_NEAR_FULL:
            mode += ", log nearly full"
        age = now - wall
        rows.append(Row(uid, mode, b.count, f"{b.battery_pct} %", clock, ok, f"{rssi} dBm",
                        "now" if age < 3 else f"{age:.0f} s ago"))
    rows.sort(key=lambda r: r.uid)
    return rows


def prefs_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".proxtool.json")


def default_outdir() -> str:
    docs = os.path.join(os.path.expanduser("~"), "Documents")
    return os.path.join(docs if os.path.isdir(docs) else os.path.expanduser("~"), "ProxTit downloads")


def load_prefs() -> dict:
    try:
        with open(prefs_path(), encoding="utf-8") as f:
            p = json.load(f)
        return p if isinstance(p, dict) else {}
    except (OSError, ValueError):
        return {}


def save_prefs(p: dict) -> None:
    try:
        with open(prefs_path(), "w", encoding="utf-8") as f:
            json.dump(p, f, indent=1)
    except OSError:
        pass                        # preferences are a convenience
