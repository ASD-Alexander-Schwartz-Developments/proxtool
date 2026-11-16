"""proxtool unit tests (no radio): python -m unittest discover -s tests"""
import os
import pathlib
import re
import struct
import unittest

from proxtool import protocol as P
from proxtool import scenario, verify

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


def tag_log(sim_uid, loop_wall0, loops, jitter=2, drop=None, extra=None):
    """Records a perfect tag would log for `loops` scenario loops."""
    recs, seq = [], 0
    for k in range(loops):
        for e in scenario.expected_encounters():
            if drop and (k, e.peer, e.start) == drop:
                continue
            uid = P.uid_bytes(scenario.peer_uid(sim_uid, e.peer))
            start = int(loop_wall0 + k * scenario.PERIOD_S + e.start + jitter)
            recs.append(P.parse_record(seq, record_bytes(start, max(1, e.duration - jitter), uid, -50, -1)))
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


if __name__ == "__main__":
    unittest.main()
