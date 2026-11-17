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


def _pct(sorted_vals: Sequence[float], p: float) -> float:
    i = min(len(sorted_vals) - 1, max(0, int(round(p / 100.0 * (len(sorted_vals) - 1)))))
    return sorted_vals[i]


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
    notes: List[str] = field(default_factory=list)
    soft_splits: List[Match] = field(default_factory=list)   # matched, split at a near-threshold silence

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
        if self.soft_splits:
            lines.append(f"accepted: {len(self.soft_splits)} encounter(s) split at a silence just under the gap "
                         f"(the detection delays on both sides made it look longer)")
        if self.matched:
            st = sorted(m.start_err for m in self.matched)
            en = sorted(m.start_err + m.dur_err for m in self.matched)
            lines.append(f"start error (logged - played): median {_pct(st, 50):+.0f} s, "
                         f"95 % {_pct(st, 95):+.0f} s, range {st[0]:+.0f}..{st[-1]:+.0f} s")
            lines.append(f"end error   (logged - played): median {_pct(en, 50):+.0f} s, "
                         f"5 % {_pct(en, 5):+.0f} s, range {en[0]:+.0f}..{en[-1]:+.0f} s")
        for n in self.notes:
            lines.append("note: " + n)
        if not (self.matched or self.missing or self.unexpected or self.far_logged):
            lines.append("RESULT: NO VERDICT YET (no complete encounter expected in the window)")
        else:
            lines.append("RESULT: " + ("PASS" if self.passed else "FAIL"))
        return "\n".join(lines)


@dataclass
class _RecRun:
    """Records of one peer that follow each other within CHAIN_S: the pieces a
    long encounter is stored in (each new piece starts where the last ended)."""
    peer: int
    wall_start: float
    wall_end: float
    pieces: List[Record]


CHAIN_S = 5             # a max-length piece and the next one touch (same second; allow clock rounding)


def _rec_runs(sim_recs: List[Tuple[float, Record]], sim_uid: str) -> List[_RecRun]:
    by_peer: dict = {}
    for w, r in sim_recs:
        by_peer.setdefault(scenario.uid_to_peer(sim_uid, r.peer), []).append((w, r))
    runs: List[_RecRun] = []
    for peer, lst in by_peer.items():
        lst.sort(key=lambda x: x[0])
        cur: Optional[_RecRun] = None
        for w, r in lst:
            if cur is not None and w - cur.wall_end <= CHAIN_S:
                cur.pieces.append(r)
                cur.wall_end = max(cur.wall_end, w + r.duration)
                continue
            cur = _RecRun(peer, w, w + r.duration, [r])
            runs.append(cur)
    runs.sort(key=lambda x: x.wall_start)
    return runs


def check(records: Sequence[Record], sim_uid: str, sim_clock: Clock, tag_clock: Clock,
          window: Tuple[float, float], silence_gap_s: int = 30, max_encounter_s: int = 900,
          tol_start_s: Optional[float] = None, tol_dur_s: Optional[float] = None) -> Report:
    """records: the tag's download. sim_clock maps wall -> scenario seconds since
    the simulator's boot, unwrapped (observed scenario time + loops); tag_clock
    maps wall -> tag clock. window: wall seconds the tag was logging the scenario.

    What is compared is whole encounters ("runs"): a long encounter is stored in
    back-to-back pieces of about the maximum length (the tag cuts on the first
    beacon after it, so a piece is a few s longer), which are joined first; each
    piece but the last must then be max_encounter_s .. max_encounter_s + gap long.

    Tolerances default to what a correct tag can do: it only knows a peer once it
    hears a beacon, so each edge of an encounter is late/early by a random
    detection delay (a few s, see the edge statistics in the summary). A delay
    as long as the silence gap would have split the encounter, so the start may
    be off by up to one gap, the duration by up to two.

    A silence the scenario plays that is shorter than the gap but within
    scenario.AMBIGUOUS_MARGIN_S of it may come out as a split (the detection delays
    on both sides add to it). Such a split is accepted and listed in `soft_splits`;
    a split at any other place is a failure."""
    if tol_start_s is None:
        tol_start_s = float(silence_gap_s)
    if tol_dur_s is None:
        tol_dur_s = 2.0 * silence_gap_s
    rep = Report()
    w0, w1 = window
    exp_runs = scenario.expected_runs(silence_gap_s)
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
    runs = _rec_runs(sim_recs, sim_uid)

    s0 = w0 + sim_clock.offset_at(w0)            # scenario seconds at the window edges
    s1 = w1 + sim_clock.offset_at(w1)

    def to_wall(scen: float) -> float:
        return scen - sim_clock.offset_at(w0 + (scen - s0))

    # Expected runs of every loop. A run is judged only if it lies inside the
    # window with room for the gap and the minute sweep at the end; the records of
    # runs cut by the window edges are not judged either.
    excluded: List[Tuple[int, float, float]] = []
    judged = []
    for loop in range(int(s0 // period) - 1, int(s1 // period) + 2):
        for e in exp_runs:
            ws = to_wall(loop * period + e.start)
            we = ws + e.duration
            if ws + e.duration + silence_gap_s + 70 <= w0 or ws >= w1:
                continue
            if ws < w0 + 5 or we + silence_gap_s + 70 > w1:
                excluded.append((e.peer, ws - tol_start_s, we + silence_gap_s + 70))
                continue
            judged.append((ws, e, [(to_wall(loop * period + a), to_wall(loop * period + b)) for a, b in e.soft]))

    used = set()
    for ws, e, soft in sorted(judged, key=lambda x: x[0]):
        we = ws + e.duration
        cand = [i for i, rr in enumerate(runs) if i not in used and rr.peer == e.peer
                and ws - tol_start_s <= rr.wall_start <= we + tol_start_s]
        m = Match(scenario.Expected(e.peer, e.start, e.duration), ws)
        if not cand:
            rep.missing.append(m)
            continue
        # Join pieces separated only at near-threshold silences of this run.
        first = cand[0]
        joined = [first]
        for i in cand[1:]:
            prev = runs[joined[-1]]
            nxt = runs[i]
            if any(abs(prev.wall_end - a) <= tol_start_s and abs(nxt.wall_start - b) <= tol_start_s
                   for a, b in soft):
                joined.append(i)
            else:
                break
        start = runs[joined[0]].wall_start
        end = runs[joined[-1]].wall_end
        se, de = start - ws, (end - start) - e.duration
        if abs(se) <= tol_start_s and abs(de) <= tol_dur_s:
            m.record, m.start_err, m.dur_err = runs[joined[0]].pieces[0], se, de
            rep.matched.append(m)
            used.update(joined)
            if len(joined) > 1:
                rep.soft_splits.append(m)
        else:
            rep.missing.append(m)

    # Piece lengths of every judged run, then left-over runs inside the window.
    for i, rr in enumerate(runs):
        if i in used:
            for p in rr.pieces[:-1]:
                if not (max_encounter_s <= p.duration <= max_encounter_s + silence_gap_s):
                    rep.unexpected.append(p)        # cut at the wrong length
            continue
        if rr.wall_start < w0 + 5 or rr.wall_end + silence_gap_s + 70 > w1:
            continue
        if any(pe == rr.peer and a <= rr.wall_start <= b for pe, a, b in excluded):
            continue
        rep.unexpected.extend(rr.pieces)
    return rep


# ---- whole bench runs: simulator restarts, tag power cuts ------------------------

@dataclass
class SimObs:
    """The simulator's status beacon heard at `wall`: uptime (s) and boot count."""
    wall: float
    uptime: float
    boots: int
    late_pct: int = 0


@dataclass
class TagObs:
    """The tag read at `wall`: its clock, boot count and uptime (s)."""
    wall: float
    tag_time: float
    boots: int
    uptime: float


@dataclass
class SimSegment:
    start: float                # wall, simulator boot
    end: float                  # wall, next boot (or the last observation if unknown)
    clock: Clock                # wall -> simulator uptime = scenario seconds since boot
    boots: int


def sim_segments(obs: Sequence[SimObs]) -> Tuple[List[SimSegment], List[str]]:
    """One segment per simulator boot that was observed. The status beacon dates
    the boot exactly (wall - uptime), so a restart between two observations is
    placed exactly too. If the boot count moved by more than one, the boots in
    between were never seen: from the last observation of the earlier boot to the
    later boot nothing can be checked."""
    notes: List[str] = []
    groups: List[List[SimObs]] = []
    for o in sorted(obs, key=lambda o: o.wall):
        if groups and groups[-1][-1].boots == o.boots and o.uptime >= groups[-1][-1].uptime:
            groups[-1].append(o)
        else:
            groups.append([o])
    segs: List[SimSegment] = []
    for i, g in enumerate(groups):
        clock = Clock([(o.wall, o.uptime) for o in g])
        start = g[0].wall - g[0].uptime
        end = float("inf")
        if i + 1 < len(groups):
            nxt = groups[i + 1][0]
            nxt_boot = nxt.wall - nxt.uptime
            jump = (nxt.boots - g[0].boots) % 256      # boot count is 8 bits in the beacon
            if jump == 1:
                end = nxt_boot
                notes.append(f"simulator restarted at {_iso(nxt_boot)} (boot {nxt.boots})")
            else:
                end = g[-1].wall
                notes.append(f"simulator restarted unobserved between {_iso(g[-1].wall)} and "
                             f"{_iso(nxt_boot)} (boot count {g[0].boots} -> {nxt.boots}): that stretch is not checked")
        segs.append(SimSegment(start, end, clock, g[0].boots))
    return segs, notes


@dataclass
class TagSegment:
    records: List[Record]
    boots: int                  # low 7 bits are what a BOOT marker carries
    clock: Optional[Clock]      # wall -> tag clock, None if this boot was never read
    boot_wall: Optional[float]  # wall time the tag (re)started, None for the first segment


def tag_segments(records: Sequence[Record], obs: Sequence[TagObs], start_boots: int) -> List[TagSegment]:
    """Split the log at BOOT markers. A tag that loses power restarts with its
    clock restored from flash (behind the real time), so each boot needs its own
    clock observation; the reads in that boot give it (and date the boot)."""
    segs: List[TagSegment] = []
    cur = TagSegment([], start_boots, None, None)
    for r in sorted(records, key=lambda r: r.seq):
        if r.marker == "BOOT":
            segs.append(cur)
            cur = TagSegment([r], r.tx_power & 0x7F, None, None)
        else:
            cur.records.append(r)
    segs.append(cur)
    for i, sg in enumerate(segs):
        mine = [o for o in obs if (o.boots & 0x7F) == (sg.boots & 0x7F)]
        if i == 0:
            mine = [o for o in obs if o.boots == start_boots]
        if mine:
            sg.clock = Clock([(o.wall, o.tag_time) for o in mine])
            if i > 0:
                sg.boot_wall = min(o.wall - o.uptime for o in mine)
    return [sg for sg in segs if sg.records or sg is segs[0]]


def check_run(records: Sequence[Record], sim_uid: str, sim_obs: Sequence[SimObs],
              tag_obs: Sequence[TagObs], start_boots: int, window: Tuple[float, float],
              silence_gap_s: int = 30, max_encounter_s: int = 900) -> Report:
    """A whole bench run: check each stretch in which both the simulator and the
    tag ran without a restart, each with its own clocks. Time the tag was off
    (power cut: from its last record before the restart to its boot) is not
    judged; the restarts are reported as notes."""
    total = Report()
    ssegs, notes = sim_segments(sim_obs)
    total.notes.extend(notes)
    tsegs = tag_segments(records, tag_obs, start_boots)
    seen: set = set()
    for j, ts in enumerate(tsegs):
        for r in ts.records:
            if r.marker:
                total.markers.append(r)
        if ts.clock is None:
            n = sum(1 for r in ts.records if not r.marker)
            total.notes.append(f"tag boot {ts.boots}: {n} records not checked (the tag was not read during that boot)")
            continue
        t_from = window[0] if j == 0 else (ts.boot_wall or window[0])
        t_to = window[1]
        if j + 1 < len(tsegs):
            ends = [r.start + r.duration - ts.clock.offset_at(r.start) for r in ts.records if not r.marker]
            t_to = max(ends) if ends else t_from
            nb = tsegs[j + 1].boot_wall
            total.notes.append(f"tag restarted (boot {tsegs[j + 1].boots}"
                               + (f" at {_iso(nb)}" if nb else "") + f"); last record before it ended {_iso(t_to)}"
                               + "; the time in between is not judged")
        for ss in ssegs:
            w0, w1 = max(t_from, ss.start), min(t_to, ss.end)
            if w1 - w0 < 300:
                continue
            rep = check(ts.records, sim_uid, ss.clock, ts.clock, (w0, w1), silence_gap_s, max_encounter_s)
            total.matched += rep.matched
            total.soft_splits += rep.soft_splits
            total.missing += rep.missing
            total.unexpected += rep.unexpected
            for lst, dst in ((rep.far_logged, total.far_logged), (rep.other_peers, total.other_peers)):
                for r in lst:
                    if r.seq not in seen:
                        seen.add(r.seq)
                        dst.append(r)
    total.matched.sort(key=lambda m: m.wall_start)
    total.missing.sort(key=lambda m: m.wall_start)
    total.unexpected.sort(key=lambda r: r.seq)
    return total


def _iso(t: float) -> str:
    import datetime as _dt
    return _dt.datetime.fromtimestamp(int(t), _dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
