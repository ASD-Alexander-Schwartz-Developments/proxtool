# Copyright 2026 A.S.D - Alexander Schwartz Developments
# SPDX-License-Identifier: Apache-2.0
"""The NCP transport and the tag protocol against a stand-in adapter (no radio):
python -m unittest discover -s tests"""
import asyncio
import struct
import threading
import unittest
from types import SimpleNamespace

from proxtool import link as L
from proxtool import ncp, protocol as P
from proxtool.tag import Tag, legacy_records, sdate_bytes, sdate_unix

TAG = "C0:FF:EE:12:34:56"


class Evt(SimpleNamespace):
    """Stands in for a pyBGAPI event: compares equal to its name."""

    def __init__(self, name, **kw):
        super().__init__(**kw)
        self._name = name

    def __eq__(self, other):
        return self._name == other if isinstance(other, str) else super().__eq__(other)

    __hash__ = object.__hash__


def rec(start, dur, peer=b"\x01\x02\x03\x04\x05\x06", rssi=-60, tx=-1):
    return struct.pack("<II", start, dur) + peer + struct.pack("<bb", rssi, tx)


class FakeTag:
    """GATT side of a tag on firmware 01.02.28 or 02.00.01."""

    def __init__(self, fw, records):
        self.fw = fw.encode()
        self.records = list(records)
        self.reply = bytes(28)
        self.clock = None
        self.head_seq = 0

    def chars(self):
        return {"00002a26-0000-1000-8000-00805f9b34fb": 0x20, P.DATACP_UUID: 0x30, P.LOG_UUID: 0x31}

    def read(self, h):
        if h == 0x20:
            return 0, self.fw
        if h == 0x30:
            return 0, self.reply
        if self.fw.startswith(b"01."):                       # one record per read, deleted
            if not self.records:
                return 0x0411, b""                         # ATT error: empty
            return 0, self.records.pop(0)
        n = min(15, len(self.records))
        return 0, bytes([n]) + struct.pack("<I", self.head_seq) + b"".join(self.records[:n])

    def write(self, h, data):
        cmd = data[0]
        if cmd == P.CMD_SETTIME:
            self.clock = sdate_unix(data[1:9])
            self.reply = bytes([cmd | 0x80]) + bytes(27)
        elif cmd == P.CMD_SETTIME_UNIX:
            self.clock = struct.unpack_from("<I", data, 1)[0]
            self.reply = bytes([cmd | 0x80]) + struct.pack("<I", self.clock) + bytes(23)
        elif cmd == P.CMD_GETPAGE:
            self.reply = bytes([cmd | 0x80]) + struct.pack("<IIII", len(self.records), self.head_seq, 0,
                                                           self.clock or 0) + bytes(11)
        elif cmd == P.CMD_LOGACK:
            first, n = struct.unpack_from("<IH", data, 1)
            k = max(0, min(n, first + n - self.head_seq))
            del self.records[:k]
            self.head_seq += k
            self.reply = bytes([cmd | 0x80]) + struct.pack("<HII", k, len(self.records), self.head_seq) + bytes(17)
        else:
            self.reply = bytes([cmd]) + bytes(27)
        return 0


class FakeLib:
    """The few pyBGAPI calls proxtool makes; events come from another thread like
    pyBGAPI's reader."""

    def __init__(self, tag):
        self.tag = tag
        self.event_handler = None
        self.connected = False
        me = self
        uuid = {u: L.uuid_to_le(u) for u in tag.chars()}
        handles = tag.chars()

        import queue
        q = queue.Queue()

        def pump():                                 # one reader thread, events in order
            while True:
                e = q.get()
                me.event_handler(e)
        threading.Thread(target=pump, daemon=True).start()

        def emit(name, **kw):
            q.put(Evt(name, **kw))

        def adv():
            payload = struct.pack("<bBI", -1, 90, 1_700_000_000) + P.uid_bytes(TAG) + struct.pack("<BBI", 1, 1, 2)
            data = bytes([4, 0x09]) + b"PRX" + bytes([len(payload) + 3, 0xFF, 0xFF, 0x02]) + payload
            emit("bt_evt_scanner_legacy_advertisement_report", address=TAG.lower(), address_type=0, rssi=-55,
                 event_flags=3, data=data)

        def done(result=0):
            emit("bt_evt_gatt_procedure_completed", connection=1, result=result)

        def read(conn, h):
            res, val = me.tag.read(h)
            if res == 0:
                emit("bt_evt_gatt_characteristic_value", connection=1, characteristic=h, att_opcode=0,
                     offset=0, value=val)
            done(res)

        def discover_chars(conn, svc):
            for u, h in handles.items():
                emit("bt_evt_gatt_characteristic", connection=1, characteristic=h, properties=0, uuid=uuid[u])
            done()

        def open_(addr, atype, phy):
            emit("bt_evt_connection_opened", address=addr, address_type=atype, role=0, connection=1,
                 bonding=255, advertiser=255, sync=0)
            emit("bt_evt_gatt_mtu_exchanged", connection=1, mtu=247)
            return SimpleNamespace(connection=1)

        def close(conn):
            emit("bt_evt_connection_closed", connection=1, reason=0x16)

        def write(conn, h, data):
            done(me.tag.write(h, bytes(data)))

        self.bt = SimpleNamespace(
            system=SimpleNamespace(reset=lambda mode: emit("bt_evt_system_boot", major=9, minor=0, patch=0,
                                                           build=1, bootloader=0, hw=0, hash=0)),
            gatt=SimpleNamespace(set_max_mtu=lambda m: None,
                                 discover_primary_services=lambda c: (emit("bt_evt_gatt_service", connection=1,
                                                                           service=7, uuid=b"\x00" * 16), done()),
                                 discover_characteristics=discover_chars,
                                 read_characteristic_value=read,
                                 write_characteristic_value=write,
                                 write_characteristic_value_without_response=lambda c, h, d: None),
            scanner=SimpleNamespace(start=lambda phy, mode: adv(), stop=lambda: None),
            connection=SimpleNamespace(open=open_, close=close),
        )
        self.__version__ = "9.0.0"

    def open(self):
        pass

    def close(self):
        pass


def run(coro):
    return asyncio.run(coro)


class Ncp(unittest.TestCase):
    def test_parse_ad(self):
        name, mfr = ncp.parse_ad(bytes([2, 1, 6, 4, 9]) + b"PRX" + bytes([4, 0xFF, 0xFF, 0x02, 0xAB]))
        self.assertEqual(name, "PRX")
        self.assertEqual(mfr, {0x02FF: b"\xab"})
        self.assertEqual(ncp.parse_ad(bytes([5, 9, 0x41])), (None, {}))        # truncated: ignored

    def test_uuid(self):
        self.assertEqual(L.uuid_from_le(L.uuid_to_le(P.DATACP_UUID)), P.DATACP_UUID)
        self.assertEqual(L.uuid_from_le(b"\x26\x2a"), "00002a26-0000-1000-8000-00805f9b34fb")

    def test_scan(self):
        t = ncp.NcpTransport(lib=FakeLib(FakeTag("02.00.01", [])))
        seen = run(t.scan(0.3))
        self.assertIn(TAG, seen)
        self.assertEqual(seen[TAG][0].count, 2)

    def test_legacy_download_and_clock(self):
        recs = [rec(1000 + i, 5 + i) for i in range(3)]
        fake = FakeTag("01.02.28", recs)
        t = ncp.NcpTransport(lib=FakeLib(fake))
        got = []

        async def go():
            async with Tag(TAG, t) as tag:
                self.assertTrue(await tag.legacy())
                await tag.set_time(1_800_000_000)
                return await tag.download(lambda r: got.extend(r), expected=3)
        self.assertEqual(run(go()), 3)
        self.assertEqual([r.start for r in got], [1000, 1001, 1002])
        self.assertTrue(all(r.seq == -1 for r in got))
        self.assertEqual(fake.clock, 1_800_000_000)                          # UTC calendar date
        self.assertEqual(fake.records, [])

    def test_new_download_acks(self):
        fake = FakeTag("02.00.01", [rec(2000 + i, 9) for i in range(20)])
        t = ncp.NcpTransport(lib=FakeLib(fake))
        got = []

        async def go():
            async with Tag(TAG, t) as tag:
                self.assertFalse(await tag.legacy())
                return await tag.download(lambda r: got.extend(r))
        self.assertEqual(run(go()), 20)
        self.assertEqual([r.seq for r in got], list(range(20)))
        self.assertEqual(fake.records, [])


class Legacy(unittest.TestCase):
    def test_records(self):
        one = rec(5, 6)
        self.assertEqual(len(legacy_records(one)), 1)
        self.assertEqual(len(legacy_records(bytes([2]) + one + one)), 2)     # 01.02.29/30 batch
        self.assertEqual(legacy_records(b""), [])
        self.assertEqual(legacy_records(b"\x05abc"), [])

    def test_sdate(self):
        import datetime as dt
        t = dt.datetime(2026, 11, 17, 21, 30, 5, tzinfo=dt.timezone.utc)
        self.assertEqual(sdate_unix(sdate_bytes(t)), int(t.timestamp()))
        self.assertEqual(sdate_bytes(t)[:2], bytes([126, 10]))                # years since 1900, month 0-11


if __name__ == "__main__":
    unittest.main()
