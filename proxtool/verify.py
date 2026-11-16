"""Compare what a tag logged against the encounters the peer simulator played.

Pure functions (no radio): proxtool bench check feeds them the downloaded
records, the simulator observations and the tag's clock offset.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from . import scenario
from .protocol import Record


@dataclass
class Clock:
    """Linear map between two clocks from (wall, other) observation pairs."""
    points: List[Tuple[float, float]]

    def offset_at(self, wall: float) -> float:
        """other - wall at a wall time, linear through the observations."""
        pts = sorted(self.points)
        if len(pts) == 1:
            return pts[0][1] - pts[0][0]
        (w0, o0), (w1, o1) = pts[0], pts[-1]
        d0, d1 = o0 - w0, o1 - w1
        if w1 == w0:
            return d0
        return d0 + (d1 - d0) * (wall - w0) / (w1 - w0)


@dataclass
class Match:
    expected: scenario.Expected
    wall_start: float
    record: Optional[Record] = None
    start_err: float = 0.0
    dur_err: float = 0.0


@dataclass
class Report:
    matched: List[Match] = field(default_factory=list)
    missing: List[Match] = field(default_factory=list)
    unexpected: List[Record] = field(default_factory=list)
    far_logged: List[Record] = field(default_factory=list)
    other_peers: List[Record] = field(default_factory=list)
    markers: List[Record] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.missing and not self.unexpected and not self.far_logged and bool(self.matched)

    def summary(self) -> str:
        lines = [
            f"expected encounters in the window: {len(self.matched) + len(self.missing)}",
            f"  matched:    {len(self.matched)}",
            f"  missing:    {len(self.missing)}",
            f"unexpected simulator records: {len(self.unexpected)}",
            f"records from the far peer:    {len(self.far_logged)}",
            f"records from other tags:      {len(self.other_peers)}",
            f"markers:                      {len(self.markers)}",
        ]
        if self.matched:
            se = max(abs(m.start_err) for m in self.matched)
            de = max(abs(m.dur_err) for m in self.matched)
            lines.append(f"worst start error {se:.0f} s, worst duration error {de:.0f} s")
        lines.append("RESULT: " + ("PASS" if self.passed else "FAIL"))
        return "\n".join(lines)


def check(records: Sequence[Record], sim_uid: str, sim_clock: Clock, tag_clock: Clock,
          window: Tuple[float, float], silence_gap_s: int = 30, max_encounter_s: int = 900,
          tol_start_s: float = 10.0, tol_dur_s: float = 12.0) -> Report:
    """records: the tag's download. sim_clock maps wall -> scenario seconds since
    the simulator's boot, unwrapped (observed scenario time + loops); tag_clock
    maps wall -> tag clock. window: wall seconds the tag was logging the scenario."""
    rep = Report()
    w0, w1 = window
    exp = scenario.expected_encounters(silence_gap_s, max_encounter_s)
    far = scenario.far_peers()
    period = scenario.PERIOD_S

    # Records: tag clock -> wall.
    sim_recs: List[Tuple[float, Record]] = []
    for r in records:
        if r.marker:
            rep.markers.append(r)
            continue
        peer = scenario.uid_to_peer(sim_uid, r.peer)
        if peer == 0:
            rep.other_peers.append(r)
            continue
        wall = r.start - tag_clock.offset_at(r.start)
        if far.get(peer):
            rep.far_logged.append(r)
            continue
        sim_recs.append((wall, r))

    # Expected encounters of every scenario loop fully inside the window. An
    # encounter is stored when the peer has been silent for the gap and the next
    # minute sweep runs, so leave that much room before the end of the window.
    s0 = w0 + sim_clock.offset_at(w0)            # scenario seconds at the window edges
    s1 = w1 + sim_clock.offset_at(w1)
    first_loop = int(s0 // period) - 1
    last_loop = int(s1 // period) + 1
    for loop in range(first_loop, last_loop + 1):
        for e in exp:
            scen_start = loop * period + e.start
            # wall time of that scenario second: invert wall + offset(wall) ~= scen
            wall = scen_start - sim_clock.offset_at(w0 + (scen_start - s0))
            if wall < w0 + 5 or wall + e.duration + silence_gap_s + 70 > w1:
                continue
            m = Match(e, wall)
            best = None
            for i, (rw, r) in enumerate(sim_recs):
                if scenario.uid_to_peer(sim_uid, r.peer) != e.peer:
                    continue
                se, de = rw - wall, r.duration - e.duration
                if abs(se) <= tol_start_s and abs(de) <= tol_dur_s:
                    if best is None or abs(se) < abs(best[1]):
                        best = (i, se, de)
            if best is None:
                rep.missing.append(m)
            else:
                i, se, de = best
                m.record, m.start_err, m.dur_err = sim_recs[i][1], se, de
                rep.matched.append(m)
                sim_recs.pop(i)

    # Left-over simulator records inside the window are errors (fragments,
    # wrong splits); ones touching the window edges are not judged.
    for rw, r in sim_recs:
        if rw >= w0 + 5 and rw + r.duration + silence_gap_s + 70 <= w1:
            rep.unexpected.append(r)
    return rep
