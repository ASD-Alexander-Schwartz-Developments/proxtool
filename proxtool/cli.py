"""proxtool command line. `proxtool -h` lists the commands."""
from __future__ import annotations

import argparse
import asyncio
import csv
import datetime as dt
import json
import os
import struct
import sys
import time
from typing import Dict, List

from . import protocol as P
from . import scenario
from . import verify

CSV_FIELDS = ["seq", "start_unix", "start_utc", "duration_s", "peer", "rssi", "tx_power", "type", "detail"]


def iso(t: int) -> str:
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def csv_path(outdir: str, uid: str) -> str:
    return os.path.join(outdir, uid.replace(":", "") + ".csv")


def append_csv(path: str, recs: List[P.Record]) -> None:
    """Append and flush to disk: called before the records are acknowledged."""
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(CSV_FIELDS)
        for r in recs:
            w.writerow([r.seq, r.start, iso(r.start), r.duration, r.peer, r.rssi, r.tx_power,
                        "marker" if r.marker else "encounter", r.describe()])
        f.flush()
        os.fsync(f.fileno())


def read_csv(path: str) -> List[P.Record]:
    out = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            out.append(P.Record(int(row["seq"]), int(row["start_unix"]), int(row["duration_s"]),
                                row["peer"], int(row["rssi"]), int(row["tx_power"])))
    # A record downloaded twice (no ack reached the tag) has the same seq: keep one.
    uniq = {r.seq: r for r in out}
    return [uniq[k] for k in sorted(uniq)]


# ---- commands ------------------------------------------------------------------

def cmd_scan(a) -> None:
    from . import ble
    seen = asyncio.run(ble.scan(a.seconds))
    if not seen:
        print("no ProxTit beacons heard")
        return
    for uid, (b, rssi, _) in sorted(seen.items()):
        if b.is_sim:
            print(f"{uid}  SIMULATOR v{b.flags}  scenario t={b.time}/{b.count} s  rssi {rssi}")
        else:
            print(f"{uid}  {P.MODES.get(b.mode, b.mode):6}  bat {b.battery_pct:3}%  log {b.count:4}  "
                  f"clock {iso(b.time)}  tx {b.tx_power:+d} dBm  rssi {rssi}  {b.flag_text()}")


def cmd_monitor(a) -> None:
    from . import ble

    def show(b, rssi, now):
        if a.address and b.uid != a.address.upper():
            return
        kind = "SIM" if b.is_sim else P.MODES.get(b.mode, b.mode)
        print(f"{time.strftime('%H:%M:%S')} {b.uid} {kind} t={b.time} log={b.count} "
              f"bat={b.battery_pct}% flags={b.flag_text()} rssi={rssi}", flush=True)

    asyncio.run(ble.scan(a.seconds, show))


def cmd_info(a) -> None:
    from . import ble

    async def run():
        async with ble.Tag(a.address) as t:
            return await t.info()
    i = asyncio.run(run())
    drift = i.time - int(time.time())
    print(f"tag {i.address}  firmware {i.firmware}")
    print(f"clock {iso(i.time)} UTC ({drift:+d} s vs this PC)")
    print(f"log: {i.page.pending} waiting, head seq {i.page.head_seq}, {i.page.overwritten} overwritten (lifetime)")
    print("config:")
    for k, v in i.config.items():
        print(f"  {k:24} {v}")
    print("stats:")
    for k, v in i.stats.items():
        print(f"  {k:24} {P.reset_cause_text(v) if k == 'reset_cause' else v}")


def cmd_settime(a) -> None:
    from . import ble

    async def run():
        async with ble.Tag(a.address) as t:
            return await t.set_time()
    tt = asyncio.run(run())
    print(f"clock set to {iso(tt)} UTC")


def cmd_getcfg(a) -> None:
    from . import ble

    async def run():
        async with ble.Tag(a.address) as t:
            return {P.REGS[r]: await t.get_cfg(r) for r in P.REGS}
    for k, v in asyncio.run(run()).items():
        print(f"{k:24} {v}")


def cmd_setcfg(a) -> None:
    from . import ble
    reg = P.REG_BY_NAME.get(a.register)
    if reg is None:
        reg = int(a.register, 0)

    async def run():
        async with ble.Tag(a.address) as t:
            ok = await t.set_cfg(reg, a.value)
            return ok, await t.get_cfg(reg)
    ok, now = asyncio.run(run())
    print(("accepted" if ok else "REJECTED") + f"; {P.REGS.get(reg, hex(reg))} = {now}")
    if not ok:
        sys.exit(1)


def download_one(address: str, outdir: str, ack: bool = True) -> str:
    from . import ble
    os.makedirs(outdir, exist_ok=True)
    path = csv_path(outdir, address.upper())

    async def run():
        async with ble.Tag(address) as t:
            def prog(n, total):
                print(f"\r  {n}/{total} records", end="", flush=True)
            n = await t.download(lambda recs: append_csv(path, recs), ack=ack, progress=prog)
            print()
            tag_time = (await t.page()).time
            return n, tag_time
    n, tag_time = asyncio.run(run())
    print(f"{n} records -> {path}  (tag clock {tag_time - int(time.time()):+d} s vs this PC)")
    return path


def cmd_download(a) -> None:
    download_one(a.address, a.out, ack=not a.no_ack)


def cmd_release(a) -> None:
    from . import ble
    if not a.yes:
        sys.exit("RELEASE fires the drop-off output. Repeat with --yes to do it.")

    async def run():
        async with ble.Tag(a.address) as t:
            return await t.release(a.ms)
    print("pulse started" if asyncio.run(run()) else "REFUSED (0 ms or a pulse running)")


# ---- bench ---------------------------------------------------------------------

def _find_sim(seconds: float):
    from . import ble
    seen = asyncio.run(ble.scan(seconds))
    sims = [(b, wall) for b, _, wall in seen.values() if b.is_sim]
    if not sims:
        sys.exit("no peer simulator (PRS beacon) heard: is it powered and in range?")
    b, wall = sims[0]
    if b.flags != scenario.VERSION or b.count != scenario.PERIOD_S:
        sys.exit(f"simulator scenario v{b.flags} / period {b.count} does not match proxtool "
                 f"v{scenario.VERSION} / {scenario.PERIOD_S}: rebuild one of them")
    return b, wall


def cmd_bench_start(a) -> None:
    from . import ble
    sim, wall = _find_sim(a.seconds)
    session = {"sim_uid": sim.uid, "sim_obs": [[wall, sim.time]], "started": time.time(), "tags": {}}
    for addr in a.tags:
        async def run():
            async with ble.Tag(addr) as t:
                for reg, val in P.DEFAULT_BENCH_CONFIG.items():
                    await t.set_cfg(reg, val)
                if a.clear:
                    page = await t.page()
                    if page.pending:
                        await t.command(P.CMD_LOGACK, struct.pack("<IH", page.head_seq, page.pending))
                tt = await t.set_time()
                return tt, await t.get_cfg(0x0A), await t.get_cfg(0x06)
        tt, gap, cap = asyncio.run(run())
        session["tags"][addr.upper()] = {"set_time": time.time(), "silence_gap_s": gap, "max_encounter_s": cap}
        print(f"{addr}: clock set {iso(tt)} UTC, silence gap {gap} s, max length {cap} s")
    with open(a.session, "w") as f:
        json.dump(session, f, indent=1)
    print(f"simulator {sim.uid} at scenario t={sim.time} s; session -> {a.session}")
    print(f"Leave the tags next to the simulator. A full scenario loop takes {scenario.PERIOD_S // 60} min;"
          f" then run: proxtool bench check {a.session}")


def _unwrap(obs: List[List[float]]) -> List[tuple]:
    """Scenario time is reported modulo the period: unwrap it along the wall clock."""
    pts = []
    w0, s0 = obs[0]
    for w, s in obs:
        expect = s0 + (w - w0)
        k = round((expect - s) / scenario.PERIOD_S)
        pts.append((w, s + k * scenario.PERIOD_S))
    return pts


def cmd_bench_check(a) -> None:
    with open(a.session) as f:
        session = json.load(f)
    if not a.offline:
        sim, wall = _find_sim(a.seconds)
        session["sim_obs"].append([wall, sim.time])
    sim_clock = verify.Clock(_unwrap(session["sim_obs"]))
    ok_all = True
    for addr, meta in session["tags"].items():
        if a.offline:
            path = csv_path(a.out, addr)
            tag_obs = meta.get("clock_obs", [[meta["set_time"], meta["set_time"]]])
        else:
            from . import ble

            async def run():
                async with ble.Tag(addr) as t:
                    p = csv_path(a.out, addr)
                    os.makedirs(a.out, exist_ok=True)
                    await t.download(lambda recs: append_csv(p, recs))
                    return p, (await t.page()).time
            path, tag_time = asyncio.run(run())
            meta.setdefault("clock_obs", [[meta["set_time"], meta["set_time"]]])
            meta["clock_obs"].append([time.time(), tag_time])
            tag_obs = meta["clock_obs"]
        recs = [r for r in read_csv(path)]
        window = (meta["set_time"], time.time() if not a.offline else meta.get("checked", time.time()))
        rep = verify.check(recs, session["sim_uid"], sim_clock, verify.Clock(tag_obs), window,
                           silence_gap_s=meta.get("silence_gap_s", 30),
                           max_encounter_s=meta.get("max_encounter_s", 900))
        meta["checked"] = window[1]
        print(f"== tag {addr} ({path})")
        print(rep.summary())
        for m in rep.missing:
            print(f"  MISSING peer {m.expected.peer:2} at {iso(int(m.wall_start))} for {m.expected.duration} s")
        for r in rep.unexpected:
            print(f"  UNEXPECTED {r.describe()} at {iso(r.start)}")
        for r in rep.far_logged:
            print(f"  FAR PEER LOGGED {r.describe()} at {iso(r.start)}")
        for r in rep.markers:
            print(f"  marker seq {r.seq}: {r.describe()} at {iso(r.start)}")
        ok_all &= rep.passed
    with open(a.session, "w") as f:
        json.dump(session, f, indent=1)
    sys.exit(0 if ok_all else 1)


def cmd_pair_check(a) -> None:
    """Two real tags near each other: each must log the other, at about the same time."""
    ra, rb = read_csv(a.csv_a), read_csv(a.csv_b)
    ua, ub = a.uid_a.upper(), a.uid_b.upper()
    ab = [r for r in ra if r.peer == ub]
    ba = [r for r in rb if r.peer == ua]
    print(f"{ua} logged {len(ab)} encounters with {ub}; {ub} logged {len(ba)} with {ua}")
    unmatched = 0
    for r in ab:
        best = min(ba, key=lambda s: abs(s.start - r.start), default=None)
        if best is None or abs(best.start - r.start) > a.tol or abs(best.duration - r.duration) > 2 * a.tol:
            unmatched += 1
            print(f"  no counterpart: {iso(r.start)} {r.duration} s")
    print("RESULT: " + ("PASS" if ab and not unmatched and len(ab) == len(ba) else "CHECK"))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="proxtool", description="ProxTit BLE tags: scan, configure, download, bench test")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="list tags and simulators in range")
    s.add_argument("-t", "--seconds", type=float, default=8)
    s.set_defaults(fn=cmd_scan)

    s = sub.add_parser("monitor", help="print every beacon heard")
    s.add_argument("address", nargs="?")
    s.add_argument("-t", "--seconds", type=float, default=3600)
    s.set_defaults(fn=cmd_monitor)

    for name, fn, hlp in (("info", cmd_info, "firmware, clock, config, log and stats"),
                          ("settime", cmd_settime, "set the tag clock from this PC (UTC)"),
                          ("getcfg", cmd_getcfg, "read all config registers")):
        s = sub.add_parser(name, help=hlp)
        s.add_argument("address")
        s.set_defaults(fn=fn)

    s = sub.add_parser("setcfg", help="write one config register (name or number)")
    s.add_argument("address")
    s.add_argument("register", help="e.g. silence_gap_s or 0x0A")
    s.add_argument("value", type=lambda v: int(v, 0))
    s.set_defaults(fn=cmd_setcfg)

    s = sub.add_parser("download", help="download the log to <out>/<address>.csv and remove it from the tag")
    s.add_argument("address")
    s.add_argument("-o", "--out", default="downloads")
    s.add_argument("--no-ack", action="store_true", help="read one batch, leave everything on the tag")
    s.set_defaults(fn=cmd_download)

    s = sub.add_parser("release", help="pulse the drop-off output (needs --yes)")
    s.add_argument("address")
    s.add_argument("ms", type=int)
    s.add_argument("--yes", action="store_true")
    s.set_defaults(fn=cmd_release)

    b = sub.add_parser("bench", help="bench test against the peer simulator").add_subparsers(dest="bcmd", required=True)
    s = b.add_parser("start", help="find the simulator, configure and clock the tags, write a session file")
    s.add_argument("tags", nargs="+", help="tag addresses")
    s.add_argument("-s", "--session", default="bench_session.json")
    s.add_argument("-t", "--seconds", type=float, default=6)
    s.add_argument("--clear", action="store_true", help="drop what is in the tags' logs first")
    s.set_defaults(fn=cmd_bench_start)
    s = b.add_parser("check", help="download the tags and compare with the scenario")
    s.add_argument("session", nargs="?", default="bench_session.json")
    s.add_argument("-o", "--out", default="downloads")
    s.add_argument("-t", "--seconds", type=float, default=6)
    s.add_argument("--offline", action="store_true", help="use the CSVs already downloaded")
    s.set_defaults(fn=cmd_bench_check)

    s = sub.add_parser("pair-check", help="two real tags: compare their logs of each other")
    s.add_argument("csv_a")
    s.add_argument("uid_a")
    s.add_argument("csv_b")
    s.add_argument("uid_b")
    s.add_argument("--tol", type=float, default=10)
    s.set_defaults(fn=cmd_pair_check)

    args = ap.parse_args(argv)
    try:
        args.fn(args)
    except Exception as e:      # bleak errors: radio off, tag out of range, ...
        if type(e).__name__.startswith("Bleak"):
            sys.exit(f"Bluetooth: {e.args[0] if e.args else e}")
        raise


if __name__ == "__main__":
    main()
