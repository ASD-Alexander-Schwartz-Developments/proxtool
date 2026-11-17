"""Mirror of the peer simulator scenario (Proxtit/peersim.c) and the encounters a
tag under test must log from it.

Keep SEGMENTS in step with peersim.c `segs[]` and VERSION with PEERSIM_VERSION.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

VERSION = 2
PERIOD_S = 3600
PEERS = 20

# (peer, start, end, far, on_s, off_s) — scenario seconds, end exclusive.
SEGMENTS: List[Tuple[int, int, int, int, int, int]] = [
    (1, 60, 660, 0, 0, 0),
    (2, 100, 2200, 0, 0, 0),
    (3, 300, 900, 0, 40, 20),
    (4, 1000, 1060, 0, 0, 0),
    (4, 1120, 1180, 0, 0, 0),
    (4, 1240, 1300, 0, 0, 0),
    (5, 0, 3600, 1, 0, 0),
    (6, 1500, 2700, 0, 30, 255),
    (7, 2400, 2700, 0, 0, 0),
    (7, 2700, 3000, 1, 0, 0),
] + [(p, 3000, 3300, 0, 0, 0) for p in range(8, 21)]


# A silence shorter than the gap but within this margin of it may be logged as a
# split: the tag hears a peer only every few seconds, so the silence it sees is
# the real one plus a detection delay on each side.
AMBIGUOUS_MARGIN_S = 20


@dataclass(frozen=True)
class Run:
    """One whole encounter (before the tag cuts it into max-length pieces)."""
    peer: int
    start: int                  # scenario second
    duration: int               # s
    soft: Tuple[Tuple[int, int], ...] = ()   # (last second heard, next start) of near-threshold silences


def expected_runs(silence_gap_s: int = 30) -> List[Run]:
    """Whole encounters of one loop, with the near-threshold silences inside them."""
    out: List[Run] = []
    for peer in range(1, PEERS + 1):
        merged: List[list] = []
        for a, b in near_intervals(peer):
            last = b - 1
            if merged and a - merged[-1][1] <= silence_gap_s:
                if a - merged[-1][1] > silence_gap_s - AMBIGUOUS_MARGIN_S:
                    merged[-1][2].append((merged[-1][1], a))
                merged[-1][1] = max(merged[-1][1], last)
            else:
                merged.append([a, last, []])
        for a, last, soft in merged:
            out.append(Run(peer, a, max(1, last - a), tuple(soft)))
    return sorted(out, key=lambda r: (r.start, r.peer))


@dataclass(frozen=True)
class Expected:
    peer: int
    start: int          # scenario second
    duration: int       # s


def near_intervals(peer: int) -> List[Tuple[int, int]]:
    """Scenario intervals [a, b) in which `peer` sends in-range beacons."""
    out: List[Tuple[int, int]] = []
    for p, start, end, far, on_s, off_s in SEGMENTS:
        if p != peer or far:
            continue
        if on_s == 0:
            out.append((start, end))
            continue
        t = start
        while t < end:
            out.append((t, min(t + on_s, end)))
            t += on_s + off_s
    return sorted(out)


def expected_encounters(silence_gap_s: int = 30, max_encounter_s: int = 900) -> List[Expected]:
    """What the tag's rules make of the scenario, one loop. A beacon is sent up
    to the last second of an interval, so an interval [a, b) is seen as a..b-1;
    the tag records first..last beacon (at least 1 s)."""
    exp: List[Expected] = []
    for peer in range(1, PEERS + 1):
        merged: List[List[int]] = []
        for a, b in near_intervals(peer):
            last = b - 1
            if merged and a - merged[-1][1] <= silence_gap_s:
                merged[-1][1] = max(merged[-1][1], last)
            else:
                merged.append([a, last])
        for a, last in merged:
            t = a
            while last - t >= max_encounter_s:
                exp.append(Expected(peer, t, max_encounter_s))
                t += max_encounter_s
            exp.append(Expected(peer, t, max(1, last - t)))
    return sorted(exp, key=lambda e: (e.start, e.peer))


def peer_uid(sim_uid: str, peer: int) -> str:
    """Virtual peer k beacons with the simulator's address, low byte = k."""
    return sim_uid[:-2] + f"{peer:02X}"


def uid_to_peer(sim_uid: str, uid: str) -> int:
    if uid[:-2] != sim_uid[:-2]:
        return 0
    k = int(uid[-2:], 16)
    return k if 1 <= k <= PEERS else 0


def far_peers() -> Dict[int, bool]:
    """Peers that are never in range (must never be logged)."""
    out = {}
    for peer in range(1, PEERS + 1):
        out[peer] = not near_intervals(peer)
    return out
