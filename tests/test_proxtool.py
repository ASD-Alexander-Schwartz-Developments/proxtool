# Copyright 2026 A.S.D - Alexander Schwartz Developments
# SPDX-License-Identifier: Apache-2.0
"""proxtool unit tests (no radio): python -m unittest discover -s tests"""
import os
import pathlib
import re
import struct
import unittest

from proxtool import protocol as P
from proxtool import dfu, model, scenario, settings, verify

PEERSIM_C = os.path.join(os.path.dirname(__file__), "..", "..", "..", "Proxtit", "peersim.c")
PEERSIM_H = os.path.join(os.path.dirname(__file__), "..", "..", "..", "Proxtit", "peersim.h")


def beacon_payload(tx=-1, bat=80, sdt=1700000000, uid=bytes([1, 2, 3, 4, 5, 6]), mode=1, flags=1, count=7):
    return struct.pack("<bBI", tx, bat, sdt) + uid + struct.pack("<BBI", mode, flags, count)


def record_bytes(start, dur, uid, rssi, tx):
    return struct.pack("<II", start, dur) + uid + struct.pack("<bb", rssi, tx)


class Protocol(unittest.TestCase):
    def test_beacon(self):
        b = P.parse_beacon({P.COMPANY_ID: beacon_payload()}, "PRX")
        self.assertEqual(b.uid, "06:05:04:03:02:01")
        self.assertEqual((b.tx_power, b.battery_pct, b.time, b.mode, b.flags, b.count),
                         (-1, 80, 1700000000, 1, 1, 7))
        self.assertFalse(b.is_sim)
        self.assertIsNone(P.parse_beacon({P.COMPANY_ID: beacon_payload()}, "XYZ"))
        self.assertIsNone(P.parse_beacon({0x1234: beacon_payload()}, "PRX"))
        self.assertTrue(P.parse_beacon({P.COMPANY_ID: beacon_payload()}, "PRS").is_sim)

    def test_uid_roundtrip(self):
        self.assertEqual(P.uid_str(P.uid_bytes("AA:BB:CC:DD:EE:0F")), "AA:BB:CC:DD:EE:0F")

    def test_log_read(self):
        uid = bytes([0x11, 0x22, 0x33, 0x44, 0x55, 0x66])
        data = bytes([2]) + struct.pack("<I", 41) + record_bytes(100, 5, uid, -50, -1) \
            + record_bytes(200, 6, bytes([2, 255, 255, 255, 255, 255]), 127, 0)
        first, recs = P.parse_log_read(data)
        self.assertEqual(first, 41)
        self.assertEqual([r.seq for r in recs], [41, 42])
        self.assertEqual(recs[0].peer, "66:55:44:33:22:11")
        self.assertIsNone(recs[0].marker)
        self.assertEqual(recs[1].marker, "TIMESET")
        self.assertIn("step +194", recs[1].describe())
        self.assertEqual(P.parse_log_read(bytes([0]) + struct.pack("<I", 9)), (9, []))
        with self.assertRaises(ValueError):
            P.parse_log_read(bytes([3]) + struct.pack("<I", 0) + bytes(16))

    def test_cp_and_replies(self):
        self.assertEqual(len(P.cp(P.CMD_LOGACK, struct.pack("<IH", 1, 2))), P.CP_LEN)
        r = bytes([P.CMD_GETPAGE | 0x80]) + struct.pack("<IIII", 5, 10, 2, 1700000000) + bytes(11)
        self.assertTrue(P.reply_ok(r, P.CMD_GETPAGE))
        self.assertEqual(P.parse_getpage(r), P.Page(5, 10, 2, 1700000000))
        r = bytes([P.CMD_LOGACK | 0x80]) + struct.pack("<HII", 3, 2, 13) + bytes(17)
        self.assertEqual(P.parse_logack(r), (3, 2, 13))
        r = bytes([P.CMD_GETSTATS | 0x80, 1]) + struct.pack("<IIIIIIH", 1, 2, 3, 4, 5, 6, 7)
        self.assertEqual(P.parse_stats(r)["split_rssi"], 7)
        self.assertEqual(P.reg_value(3, 0xFFF6), -10)


class Scenario(unittest.TestCase):
    @unittest.skipUnless(os.path.exists(PEERSIM_C), "firmware sources not here (stand-alone proxtool)")
    def test_matches_peersim_c(self):
        """scenario.py must mirror the simulator firmware's table."""
        src = pathlib.Path(PEERSIM_C).read_text(encoding="utf-8")
        body = src[src.index("segs[] = {"):src.index("};", src.index("segs[] = {"))]
        rows = [tuple(int(x) for x in m.groups())
                for m in re.finditer(r"\{\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\s*\}", body)]
        self.assertEqual(rows, scenario.SEGMENTS)
        hdr = pathlib.Path(PEERSIM_H).read_text(encoding="utf-8")
        self.assertIn(f"#define PEERSIM_VERSION      {scenario.VERSION}", hdr)
        self.assertIn(f"#define PEERSIM_PERIOD_S     {scenario.PERIOD_S}u", hdr)
        self.assertIn(f"#define PEERSIM_PEERS        {scenario.PEERS}", hdr)

    def test_expected(self):
        exp = scenario.expected_encounters()
        by = {}
        for e in exp:
            by.setdefault(e.peer, []).append(e)
        self.assertEqual([(e.start, e.duration) for e in by[1]], [(60, 599)])
        self.assertEqual([(e.start, e.duration) for e in by[2]], [(100, 900), (1000, 900), (1900, 299)])
        self.assertEqual(len(by[3]), 1)                       # 20 s silences merge
        self.assertEqual([e.duration for e in by[4]], [59, 59, 59])   # 60 s silences split
        self.assertNotIn(5, by)                               # always far
        self.assertEqual([e.duration for e in by[6]], [29] * 5)
        self.assertEqual([(e.start, e.duration) for e in by[7]], [(2400, 299)])
        self.assertEqual(sum(1 for p in range(8, 21) if by.get(p)), 13)
        self.assertEqual(len(exp), 27)


def piece_len(expected, jitter, max_s=900):
    """What the tag stores: a max-length piece is cut on the first beacon after
    max_s (a little longer); other encounters lose a little at the edges."""
    return expected + jitter if expected >= max_s else max(1, expected - jitter)


def tag_log(sim_uid, loop_wall0, loops, jitter=2, drop=None, extra=None):
    """Records a perfect tag would log for `loops` scenario loops."""
    recs, seq = [], 0
    for k in range(loops):
        for e in scenario.expected_encounters():
            if drop and (k, e.peer, e.start) == drop:
                continue
            uid = P.uid_bytes(scenario.peer_uid(sim_uid, e.peer))
            start = int(loop_wall0 + k * scenario.PERIOD_S + e.start + jitter)
            recs.append(P.parse_record(seq, record_bytes(start, piece_len(e.duration, jitter), uid, -50, -1)))
            seq += 1
    for r in extra or []:
        recs.append(r)
    return recs


class Verify(unittest.TestCase):
    SIM = "C0:FF:EE:00:11:22"
    W0 = 1_700_000_000

    def run_check(self, recs, loops=2):
        # Simulator booted at W0 - 100: scenario t = wall - (W0 - 100).
        sim = verify.Clock([(self.W0, 100), (self.W0 + 7200, 7300)])
        tag = verify.Clock([(self.W0, self.W0)])
        window = (self.W0, self.W0 + loops * scenario.PERIOD_S + 400)
        return verify.check(recs, self.SIM, sim, tag, window)

    def test_pass(self):
        rep = self.run_check(tag_log(self.SIM, self.W0 - 100, 3))
        self.assertTrue(rep.passed, rep.summary())
        self.assertGreater(len(rep.matched), 40)

    def test_missing(self):
        rep = self.run_check(tag_log(self.SIM, self.W0 - 100, 3, drop=(1, 4, 1120)))
        self.assertFalse(rep.passed)
        self.assertEqual([(m.expected.peer, m.expected.start) for m in rep.missing], [(4, 1120)])

    def test_fragment_and_far(self):
        frag = P.parse_record(999, record_bytes(self.W0 - 100 + 3600 + 500, 20,
                                                P.uid_bytes(scenario.peer_uid(self.SIM, 1)), -50, -1))
        far = P.parse_record(1000, record_bytes(self.W0 + 100, 20,
                                                P.uid_bytes(scenario.peer_uid(self.SIM, 5)), -50, -1))
        other = P.parse_record(1001, record_bytes(self.W0 + 100, 20, bytes(6), -50, -1))
        rep = self.run_check(tag_log(self.SIM, self.W0 - 100, 3, extra=[frag, far, other]))
        self.assertFalse(rep.passed)
        self.assertEqual(len(rep.unexpected), 1)
        self.assertEqual(len(rep.far_logged), 1)
        self.assertEqual(len(rep.other_peers), 1)

    def test_tag_clock_drift(self):
        """A tag clock running 1 s per 10 min fast is corrected from the two observations."""
        recs = tag_log(self.SIM, self.W0 - 100, 3, jitter=0)
        for r in recs:
            r.start += int((r.start - self.W0) / 600)
        sim = verify.Clock([(self.W0, 100), (self.W0 + 7200, 7300)])
        tag = verify.Clock([(self.W0, self.W0), (self.W0 + 7600, self.W0 + 7600 + 12)])
        rep = verify.check(recs, self.SIM, sim, tag, (self.W0, self.W0 + 7600), tol_start_s=3)
        self.assertTrue(rep.passed, rep.summary())


def run_log(sim_uid, sim_boot, w_from, w_to, tag_offset=0, seq0=0, jitter=2):
    """Records a correct tag logs while the simulator (booted at wall sim_boot)
    plays between w_from and w_to; tag clock = wall + tag_offset."""
    recs, seq = [], seq0
    k = int((w_from - sim_boot) // scenario.PERIOD_S) - 1
    while sim_boot + k * scenario.PERIOD_S < w_to:
        for e in scenario.expected_encounters():
            w = sim_boot + k * scenario.PERIOD_S + e.start + jitter
            if w < w_from or w + e.duration + 30 > w_to:
                continue
            uid = P.uid_bytes(scenario.peer_uid(sim_uid, e.peer))
            recs.append(P.parse_record(seq, record_bytes(int(w + tag_offset), piece_len(e.duration, jitter),
                                                         uid, -50, -1)))
            seq += 1
        k += 1
    recs.sort(key=lambda r: r.start)
    for i, r in enumerate(recs):
        r.seq = seq0 + i
    return recs


def boot_marker(seq, tag_time, boots):
    return P.parse_record(seq, record_bytes(tag_time, 1, bytes([1, 255, 255, 255, 255, 255]), 127, boots))


class Run(unittest.TestCase):
    """verify.check_run: whole runs with restarts and power cuts."""
    SIM = "C0:FF:EE:00:11:22"
    W0 = 1_700_000_000

    def test_sim_restart_observed(self):
        boot_a, boot_b = self.W0 - 100, self.W0 + 5000
        end = self.W0 + 4 * 3600
        recs = run_log(self.SIM, boot_a, self.W0, boot_b) + run_log(self.SIM, boot_b, boot_b, end, seq0=500)
        sim = [verify.SimObs(self.W0, 100, 5), verify.SimObs(end, end - boot_b, 6)]
        tag = [verify.TagObs(self.W0, self.W0, 3, 50), verify.TagObs(end, end, 3, 50 + end - self.W0)]
        rep = verify.check_run(recs, self.SIM, sim, tag, 3, (self.W0, end))
        self.assertTrue(rep.passed, rep.summary())
        self.assertTrue(any("restarted at" in n for n in rep.notes), rep.notes)
        self.assertGreater(len(rep.matched), 60)

    def test_sim_restart_unobserved(self):
        """Two restarts, one never seen: its stretch is skipped, not failed."""
        boot_a, boot_b, boot_c = self.W0 - 100, self.W0 + 5000, self.W0 + 9000
        end = self.W0 + 5 * 3600
        recs = (run_log(self.SIM, boot_a, self.W0, boot_b) + run_log(self.SIM, boot_b, boot_b, boot_c, seq0=300)
                + run_log(self.SIM, boot_c, boot_c, end, seq0=600))
        sim = [verify.SimObs(self.W0, 100, 5), verify.SimObs(end, end - boot_c, 7)]
        tag = [verify.TagObs(self.W0, self.W0, 3, 50), verify.TagObs(end, end, 3, 50 + end - self.W0)]
        rep = verify.check_run(recs, self.SIM, sim, tag, 3, (self.W0, end))
        self.assertTrue(rep.passed, rep.summary())
        self.assertTrue(any("unobserved" in n for n in rep.notes), rep.notes)

    def test_tag_power_cut(self):
        """Power lost for 2 h; the tag comes back with its clock 2 h behind."""
        boot = self.W0 - 100
        cut, back = self.W0 + 3 * 3600 + 200, self.W0 + 5 * 3600
        end = self.W0 + 8 * 3600
        before = run_log(self.SIM, boot, self.W0, cut)
        lag = back - cut                                   # tag clock restored to ~the cut time
        after = run_log(self.SIM, boot, back, end, tag_offset=-lag, seq0=len(before) + 1)
        recs = before + [boot_marker(len(before), cut, 4)] + after
        sim = [verify.SimObs(self.W0, 100, 5), verify.SimObs(end, end - boot, 5)]
        tag = [verify.TagObs(self.W0, self.W0, 3, 50), verify.TagObs(end, end - lag, 4, end - back)]
        rep = verify.check_run(recs, self.SIM, sim, tag, 3, (self.W0, end))
        self.assertTrue(rep.passed, rep.summary())
        self.assertTrue(any("tag restarted" in n for n in rep.notes), rep.notes)
        self.assertEqual(len(rep.markers), 1)

    def test_tag_boot_never_read(self):
        """A boot with no clock reading cannot be placed in time: reported, not judged."""
        boot = self.W0 - 100
        cut = self.W0 + 2 * 3600 + 200
        before = run_log(self.SIM, boot, self.W0, cut)
        after = run_log(self.SIM, boot, cut + 600, cut + 7200, tag_offset=-600, seq0=len(before) + 1)
        recs = before + [boot_marker(len(before), cut, 4)] + after
        sim = [verify.SimObs(self.W0, 100, 5)]
        tag = [verify.TagObs(self.W0, self.W0, 3, 50)]
        rep = verify.check_run(recs, self.SIM, sim, tag, 3, (self.W0, cut + 7200))
        self.assertTrue(any("not checked" in n for n in rep.notes), rep.notes)
        self.assertEqual(rep.unexpected, [])

    def test_split_detected(self):
        """A crowd encounter logged in two pieces is a failure."""
        boot = self.W0 - 100
        end = self.W0 + 2 * 3600
        recs = run_log(self.SIM, boot, self.W0, end)
        victim = next(r for r in recs if r.peer == scenario.peer_uid(self.SIM, 12))
        half = victim.duration // 2
        tail = P.parse_record(9999, record_bytes(victim.start + half + 40, victim.duration - half - 40,
                                                 P.uid_bytes(victim.peer), -50, -1))
        victim.duration = half
        sim = [verify.SimObs(self.W0, 100, 5)]
        tag = [verify.TagObs(self.W0, self.W0, 3, 50)]
        rep = verify.check_run(recs + [tail], self.SIM, sim, tag, 3, (self.W0, end))
        self.assertFalse(rep.passed)
        self.assertEqual(len(rep.missing), 1)

    def test_soft_split_accepted(self):
        """Peer 3's 20 s silences are 10 s under the gap: a split there is accepted
        (and listed); the same split of peer 1, which has no silence, fails."""
        boot = self.W0 - 100
        end = self.W0 + 2 * 3600
        sim = [verify.SimObs(self.W0, 100, 5)]
        tag = [verify.TagObs(self.W0, self.W0, 3, 50)]

        def split(recs, peer, at_scen, gap):
            v = next(r for r in recs if r.peer == scenario.peer_uid(self.SIM, peer) and r.start > self.W0 + 600)
            cut = int(v.start - (v.start - boot) % scenario.PERIOD_S + at_scen) - v.start
            tail = P.parse_record(9999, record_bytes(v.start + cut + gap, v.duration - cut - gap,
                                                     P.uid_bytes(v.peer), -50, -1))
            v.duration = cut
            return recs + [tail]

        # Peer 3 is on 300-339, silent 340-359: heard until ~337, again from ~365.
        recs = split(run_log(self.SIM, boot, self.W0, end), 3, 337, 28)
        rep = verify.check_run(recs, self.SIM, sim, tag, 3, (self.W0, end))
        self.assertTrue(rep.passed, rep.summary())
        self.assertEqual(len(rep.soft_splits), 1)
        recs = split(run_log(self.SIM, boot, self.W0, end), 1, 337, 31)
        rep = verify.check_run(recs, self.SIM, sim, tag, 3, (self.W0, end))
        self.assertFalse(rep.passed)

    def test_encounter_in_progress_at_start(self):
        """Peer 2 already in range when the run starts: the tag's pieces are offset
        from the scenario's 900 s boundaries; that encounter is not judged."""
        boot = self.W0 - 400                       # scenario t = 400 at the start: peer 2 since t = 100
        end = self.W0 + 2 * 3600
        recs = [r for r in run_log(self.SIM, boot, self.W0 + 3600, end)]
        uid = P.uid_bytes(scenario.peer_uid(self.SIM, 2))
        first = [P.parse_record(800, record_bytes(self.W0 + 2, 906, uid, -50, -1)),
                 P.parse_record(801, record_bytes(self.W0 + 908, 890, uid, -50, -1))]   # peer 2 leaves at W0 + 1799
        sim = [verify.SimObs(self.W0, 400, 5)]
        tag = [verify.TagObs(self.W0, self.W0, 3, 50)]
        rep = verify.check_run(recs + first, self.SIM, sim, tag, 3, (self.W0, end))
        self.assertEqual([r for r in rep.unexpected if r.seq >= 800], [], rep.summary())
        self.assertFalse(any(m.expected.peer == 2 and m.wall_start < self.W0 + 1900 for m in rep.missing))


class Settings(unittest.TestCase):
    def test_parse_and_display(self):
        tx = settings.BY_REG[0x03]
        self.assertEqual(tx.parse("-1.0"), (-10, ""))
        self.assertEqual(tx.parse("2,5")[0], 25)
        self.assertIsNone(tx.parse("7")[0])                 # above +6.0 dBm
        self.assertEqual(tx.to_display(-10), "-1.0")
        gap = settings.BY_REG[0x0A]
        self.assertEqual(gap.parse("45"), (45, ""))
        self.assertIsNone(gap.parse("1")[0])                # floor 2 s
        self.assertIsNone(gap.parse("abc")[0])
        mode = settings.BY_REG[0x00]
        self.assertEqual(mode.parse("off")[0], 0)
        self.assertEqual(mode.to_display(1), "Logger")
        self.assertIn("unknown", mode.to_display(2))

    def test_defaults_match_bench_config(self):
        """The window's defaults are the firmware's (same source as bench start)."""
        for reg, val in P.DEFAULT_BENCH_CONFIG.items():
            s = settings.BY_REG.get(reg)
            if s is not None:
                self.assertEqual(int(round(s.default * s.scale)), val, s.label)

    @unittest.skipUnless(os.path.exists(PEERSIM_C), "firmware sources not here (stand-alone proxtool)")
    def test_defaults_match_firmware(self):
        src = pathlib.Path(PEERSIM_C).with_name("proxtit_types.h").read_text(encoding="utf-8")
        for name, reg in (("PROX_BEACON_IVAL_DEFAULT_MS", 0x01), ("PROX_BEACON_DURN_DEFAULT", 0x02),
                          ("PROX_SCAN_IVAL_DEFAULT_MS", 0x04), ("PROX_SCAN_WINDOW_DEFAULT_MS", 0x07),
                          ("PROX_SILENCE_GAP_DEFAULT", 0x0A), ("PROX_MAX_ENCOUNTER_DEFAULT", 0x06)):
            m = re.search(r"#define\s+" + name + r"\s+(\d+)", src)
            self.assertIsNotNone(m, name)
            self.assertEqual(int(m.group(1)), settings.BY_REG[reg].default, name)

    def test_write_order(self):
        cur = {0x04: 1000, 0x07: 35, 0x00: 1}
        grow = settings.write_order({0x07: 2000, 0x04: 5000, 0x00: 0, 0x0A: 60}, cur)
        self.assertEqual([r for r, _ in grow], [0x0A, 0x04, 0x07, 0x00])   # interval before a bigger window, mode last
        shrink = settings.write_order({0x07: 20, 0x04: 500}, cur)
        self.assertEqual([r for r, _ in shrink], [0x07, 0x04])
        self.assertEqual(settings.changed(cur, {0x04: 1000, 0x07: 50}), {0x07: 50})


class Model(unittest.TestCase):
    def test_rows(self):
        now = 1_700_000_000.0
        tag = P.Beacon("PRX", "AA:BB:CC:DD:EE:01", -1, 90, int(now), 1, P.FLAG_TIME_SET, 12)
        unset = P.Beacon("PRX", "AA:BB:CC:DD:EE:02", -1, 90, 5000, 1, 0, 0)
        late = P.Beacon("PRX", "AA:BB:CC:DD:EE:03", -1, 90, int(now) - 60, 1, P.FLAG_TIME_SET, 0)
        sim = P.Beacon("PRS", "11:22:33:44:55:F1", 0, 8, 100, 0xA5, 2, 3600)
        old = P.Beacon("PRX", "AA:BB:CC:DD:EE:04", -1, 90, int(now), 1, P.FLAG_TIME_SET, 0)
        seen = {b.uid: (b, -60, now) for b in (tag, unset, late, sim)}
        seen[old.uid] = (old, -60, now - 1000)
        rows = {r.uid: r for r in model.tag_rows(seen, now)}
        self.assertEqual(set(rows), {tag.uid, unset.uid, late.uid})          # no simulator, no stale tag
        peer = P.Beacon("PRX", "11:22:33:44:55:07", -1, 0, 100, 1, 0, 0)       # a simulator's virtual peer
        seen[peer.uid] = (peer, -60, now)
        self.assertNotIn(peer.uid, {r.uid for r in model.tag_rows(seen, now)})
        self.assertTrue(rows[tag.uid].clock_ok)
        self.assertEqual(rows[tag.uid].records, 12)
        self.assertEqual(rows[unset.uid].clock, "NOT SET")
        legacy = P.Beacon("PRX", "AA:BB:CC:DD:EE:05", -1, 90, int(now), 1, 0, 3)   # 01.02.x: flag never set
        seen[legacy.uid] = (legacy, -60, now)
        r = {r.uid: r for r in model.tag_rows(seen, now)}[legacy.uid]
        self.assertTrue(r.clock_ok)
        self.assertTrue(model.due(r, now, 0))                                     # records waiting
        self.assertFalse(model.due(r, now, now - 10))                             # visited 10 s ago
        self.assertFalse(model.due(rows[tag.uid].__class__(**{**rows[tag.uid].__dict__, "records": 0}), now, 0))
        self.assertIn("off by", rows[late.uid].clock)


class Dfu(unittest.TestCase):
    GBL = os.path.join(os.path.dirname(__file__), "..", "..", "..", "Proxtit", "cmake_gcc", "build",
                       "images", "proxtit-02.00.01.gbl")

    def fake_gbl(self, version=b"02.00.01"):
        return (struct.pack("<II", dfu.GBL_HEADER_TAG, 8) + bytes(8) + struct.pack("<I", dfu.GBL_APP_TAG)
                + b"\x00" * 40 + b"00.00.00\x00" + version + b"\x00" + bytes(64))

    def test_check(self):
        info = dfu.check_gbl(self.fake_gbl())
        self.assertEqual(info.version, "02.00.01")
        with self.assertRaises(ValueError):
            dfu.check_gbl(b"\x00" * 100)                         # wrong header
        with self.assertRaises(ValueError):
            dfu.check_gbl(self.fake_gbl()[:20])                   # too small
        no_app = self.fake_gbl().replace(struct.pack("<I", dfu.GBL_APP_TAG), bytes(4))
        with self.assertRaises(ValueError):
            dfu.check_gbl(no_app)

    @unittest.skipUnless(os.path.exists(GBL), "built firmware image not present")
    def test_real_image(self):
        with open(self.GBL, "rb") as f:
            self.assertIsNotNone(dfu.check_gbl(f.read()).version)

    def test_chunks_and_address(self):
        self.assertEqual(dfu.chunk_size(247), 244)
        self.assertEqual(dfu.chunk_size(23), 20)
        self.assertEqual(dfu.chunk_size(100) % 4, 0)
        data = bytes(range(250)) * 3
        self.assertEqual(b"".join(dfu.chunks(data, 244)), data)
        self.assertEqual(dfu.address_plus_one("C0:FF:EE:12:34:56"), "C0:FF:EE:12:34:57")
        self.assertEqual(dfu.address_plus_one("C0:FF:EE:12:34:FF"), "C0:FF:EE:12:35:00")


if __name__ == "__main__":
    unittest.main()
