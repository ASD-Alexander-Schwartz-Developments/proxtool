# Copyright 2026 A.S.D - Alexander Schwartz Developments
# SPDX-License-Identifier: Apache-2.0
"""User-facing description of the tag settings (config registers): label, unit,
limits and help text, and the conversion between what a user types and the raw
register value. Used by the window (gui.py); no radio, so it is unit-tested.

Limits follow the firmware (Proxtit/app.c, config write); defaults follow
Proxtit/proxtit_types.h and params.c (02.00.01).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class Setting:
    reg: int
    label: str
    unit: str
    lo: float
    hi: float
    default: float
    help: str
    advanced: bool = False
    scale: float = 1.0                  # shown value = raw / scale (TX power: 0.1 dBm -> dBm)
    signed: bool = False
    choices: Optional[Dict[int, str]] = None
    since: str = ""                     # firmware that has it; older firmware reads it as 0

    def missing(self, raw: Optional[int]) -> bool:
        """True when the tag's firmware predates this setting (it reads 0, below the range)."""
        return bool(self.since) and (raw is None or raw < self.lo)

    def to_display(self, raw: int) -> str:
        if self.choices is not None:
            return self.choices.get(raw, f"{raw} (unknown)")
        v = raw / self.scale
        return f"{v:.1f}" if self.scale != 1 else str(int(v))

    def parse(self, text: str) -> Tuple[Optional[int], str]:
        """User text -> raw register value, or (None, why not)."""
        text = text.strip()
        if self.choices is not None:
            for raw, name in self.choices.items():
                if text.lower() == name.lower() or text == str(raw):
                    return raw, ""
            return None, f"choose one of: {', '.join(self.choices.values())}"
        try:
            v = float(text.replace(",", "."))
        except ValueError:
            return None, "not a number"
        if not (self.lo <= v <= self.hi):
            return None, f"must be {self._fmt(self.lo)} to {self._fmt(self.hi)} {self.unit}".rstrip()
        raw = int(round(v * self.scale))
        return raw, ""

    def _fmt(self, v: float) -> str:
        return f"{v:.1f}" if self.scale != 1 else f"{int(v)}"


SETTINGS: List[Setting] = [
    Setting(0x00, "Mode", "", 0, 1, 1,
            "Logger: beacons, listens for peers and logs encounters. Off: the tag sleeps; "
            "wake it with the magnet to connect again.",
            choices={0: "Off", 1: "Logger"}),
    Setting(0x05, "Proximity threshold", "dB", 0, 200, 85,
            "A peer counts as close when the path loss (its TX power minus the received signal) "
            "is below this. Higher = counts peers further away as close."),
    Setting(0x0A, "Silence time", "s", 2, 65535, 30,
            "No beacon from a peer for this long ends the encounter. A per-study choice: see the "
            "user guide, 'Choosing the silence time'. Shorter splits more (splits can be merged "
            "in the analysis); longer merges short separations (cannot be undone)."),
    Setting(0x06, "Maximum encounter length", "s", 1, 65535, 900,
            "A longer encounter is stored in back-to-back records of this length."),
    Setting(0x03, "TX power", "dBm", -50.0, 6.0, -1.0,
            "Beacon power. Higher = this tag is heard further away by every other tag. The tag "
            "stores the nearest power the radio supports.", scale=10, signed=True),
    Setting(0x01, "Beacon interval", "ms", 100, 40000, 100,
            "Time between beacons. Shorter = peers hear this tag more often (better detection), "
            "more battery.", advanced=True),
    Setting(0x02, "Beacon duration", "x100 ms", 0, 100, 1,
            "Advert burst per beacon. At least the interval = advertise continuously (default); "
            "0 = a single advert per beacon.", advanced=True),
    Setting(0x04, "Scan interval", "ms", 4, 65535, 1000,
            "Listening period. The tag listens for 'scan window' ms of every 'scan interval' ms.",
            advanced=True),
    Setting(0x07, "Scan window", "ms", 1, 65535, 35,
            "Listening time per scan interval. Longer = hears peers more often, more battery "
            "(listening is the largest battery cost).", advanced=True),
    Setting(0x0B, "Level-change split", "dB", 0, 60, 0,
            "When the path loss stays more than this away from the encounter's average for the "
            "hold time, a new record starts there (the animals moved closer or apart). 0 = never "
            "(default). Choose it from a calibration: about the difference "
            "between two distances you want told apart. Before firmware 02.01.00 a single jump split."),
    Setting(0x0C, "Level-change hold", "s", 2, 600, 10,
            "How long a level change must last before it splits (and at least 3 beacons). Shorter "
            "changes (posture, body shading) stay in the record's average.", since="02.01.00"),
]

BY_REG = {s.reg: s for s in SETTINGS}


def changed(current: Dict[int, int], wanted: Dict[int, int]) -> Dict[int, int]:
    """The registers whose wanted raw value differs from the tag's current one."""
    return {reg: v for reg, v in wanted.items() if current.get(reg) != v}


def write_order(regs: Dict[int, int], current: Dict[int, int]) -> List[Tuple[int, int]]:
    """Order the writes so the firmware's cross-checks do not clamp them: the scan
    window must not exceed the scan interval at any step, and the mode goes last
    (Off puts the tag to sleep)."""
    items = list(regs.items())
    grow = regs.get(0x07, current.get(0x07, 0)) > current.get(0x07, 0)

    def key(item):
        reg = item[0]
        if reg == 0x00:
            return 99
        if reg in (0x04, 0x07):
            # Growing the window: interval first. Shrinking it: window first.
            if reg == 0x04:
                return 10 if grow else 11
            return 11 if grow else 10
        return 0
    return sorted(items, key=key)
