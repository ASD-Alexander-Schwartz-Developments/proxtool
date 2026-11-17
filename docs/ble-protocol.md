<!-- Copyright 2026 A.S.D - Alexander Schwartz Developments. SPDX-License-Identifier: Apache-2.0 -->
# ProxTit BLE protocol

How a PC (e.g. [proxtool](../README.md)), phone or base station finds ProxTit tags,
configures them, sets their clock, downloads their logged encounters and updates
their firmware over Bluetooth LE. Tag firmware **02.00.00** and later; the
differences from 01.02.x are listed at the end.

This document is the public, normative description of the protocol; proxtool
(`proxtool/protocol.py`, `ble.py`, `dfu.py`) implements it.

Custom GATT service `PRX` (UUID `01e59576-be13-47da-9c29-354a565cc874`), two
characteristics:

- **`prx_datacp`** (UUID `8093f8a5-82ce-4fac-9fb3-f7dab64c0b74`) — control point,
  read/write. Command = `gapp_cp_cmd_t {u8 cmd; u8 data[27]}`; reply =
  `gapp_cp_reply_t {u8 rcmd; u8 data[27]}`, which the central **reads back** after
  the write (the characteristic has read + write properties only; there is no
  notify or indicate). `rcmd = cmd | 0x80` on success.
- **`prx_log`** (UUID `1d316924-9f39-47a3-a16d-a39846473eac`) — read-only bulk
  stream: encounter batches in logger mode, modem results in BLE-modem mode (see
  *BLE-modem commands*).

All numbers are little-endian.

## Beacon

Every tag advertises (connectable, device name `PRX`) a manufacturer-specific AD,
company ID `0x02FF` (bytes `FF 02`), followed by:

| Offset | Field | |
|---|---|---|
| 0 | `i8 tx_power` | dBm the tag transmits at (whole dBm of reg 0x03) |
| 1 | `u8 battery` | 0–100 % (3.0 V = 0 %, 4.2 V = 100 %) |
| 2 | `u32 time` | tag clock, Unix seconds |
| 6 | `u8 uid[6]` | tag id = its BLE identity address (`addr[0]` = LSB) |
| 12 | `u8 mode` | 0 off · 1 logger · 2 modem |
| 13 | `u8 flags` | bit 0 clock set since boot · bit 1 log ≥ 90 % full · bit 2 low battery |
| 14 | `u32 count` | records in the log waiting for download |

Other tags key encounters on `uid`, not on the advertiser address. ASD's bench peer
simulator sends the same layout named `PRS` (tags ignore it; proxtool's bench
commands use it).

## Control-point commands (`prx_datacp` write, then read the reply)

| cmd | Name | Request `data` | Reply `data` |
|-----|------|----------------|--------------|
| 0x08 | **RELEASE** | `u16 width_ms` (1–65535) | echoes `u16 width_ms`; `rcmd|0x80` = pulse started. **Not authenticated.** |
| 0x09 | GETTIME | — | `sdate_time_t` (current tag time) |
| 0x0A | SETTIME | `sdate_time_t` | — `rcmd|0x80` only if the date was valid and set |
| 0x10 | SETCFG | `u16 reg, u16 value` | validated, applied live + persisted; `rcmd|0x80` on valid. **Not authenticated.** |
| 0x11 | GETCFG | `u16 reg` | `u16 reg, u16 value` |
| 0x12 | **GETPAGE** | — | `u32 pending, u32 head_seq, u32 overwritten, u32 time` |
| 0x13 | **LOGACK** | `u32 first_seq, u16 count` | `u16 removed, u32 pending, u32 head_seq` |
| 0x14 | **GETSTATS** | `u8 page` | `u8 page` + the page (below); unknown page → plain `rcmd` |
| 0x15 | **SETTIME_UNIX** | `u32 unix_time` | `u32 time` (tag clock after the change) |
| 0x20–0x23 | — | reserved (add-on modem mode, not part of this document) | |

`sdate_time_t` = `{u8 year (since 1900), u8 month (0–11), u8 day (1–31), u8 hour,
u8 min, u8 sec, u16 ms}` (ms ignored) — the same encoding GETTIME returns.

Config registers (u16 each; defaults of firmware 02.00.01). SETCFG validates and
applies a value at once and keeps it in flash; out-of-range values are clamped or
rejected as listed. GETCFG returns what the tag actually uses.

| reg | Name | Unit | Default | Range / notes |
|---|---|---|---|---|
| 0x00 | mode | | 1 | 0 off (sleeps; wake with a magnet), 1 logger, 2 modem (add-on only) |
| 0x01 | beacon_interval | ms | 100 | 100–40000 |
| 0x02 | beacon_duration | ×100 ms | 1 | 0–100; 0 = one advertising event per beacon; ≥ interval = continuous advertising |
| 0x03 | tx_power | **0.1 dBm, signed** | −10 | −500…+60; the tag stores the nearest power its radio supports |
| 0x04 | scan_interval | ms | 1000 | ≥ 4 and ≥ scan_window |
| 0x05 | proximity_threshold | dB path loss | 85 | a peer is close when (its TX power − RSSI) is below this |
| 0x06 | max_encounter | s | 900 | longer encounters are stored as back-to-back records of this length |
| 0x07 | scan_window | ms | 35 | ≤ scan_interval; the radio listens the whole window |
| 0x08, 0x09 | turn_on, turn_off | | 0 | reserved: stored (`hour << 8 \| minute`, validated) but not used by 02.00.x |
| 0x0A | silence_gap | s | 30 | 2–65535: no beacon from a peer for this long ends its encounter |
| 0x0B | rssi_split | dB | 0 | 0–60: a signal change of more than this starts a new record; 0 = never |

The `tx_power` byte in the beacon and in a record is whole dBm.

### Setting the clock

SETTIME and SETTIME_UNIX set the tag clock. A step of more than 2 s first stores
every open encounter (their times are in the old time base) and adds a
**TIMESET** marker to the log; the new time is saved to flash and restored at the
next boot. Set the clock after every power-up (beacon flag bit 0 clear = not set
since boot).

### GETSTATS pages

| page | fields |
|---|---|
| 0 health | `u32 uptime_s, u32 boot_count, u32 reset_cause, u16 vbat_mv, u16 vbat_min_mv, u32 nvm_errors, u32 log_overwritten, u8 open_encounters, u8 flags` |
| 1 encounters (since boot) | `u32 beacons, u32 far, u32 opened, u32 logged, u32 dropped_full, u32 split_max, u16 split_rssi` |
| 2 log/clock | `u32 time, u32 log_count, u32 head_seq, u8 mode` |

`reset_cause` is the EFR32BG22 `EMU->RSTCAUSE` register at boot: bit 0 power-on,
1 reset pin, 2 EM4 wake-up (magnet), 3 watchdog, 5 core lockup, 6 software reset,
7–11 brown-out (DVDD, DVDD LE, DEC, AVDD, IOVDD0). `beacons` = PRX beacons heard, `far` = of
those past the proximity threshold, `dropped_full` = beacons from a new peer while
64 encounters were open (that peer was not tracked).

## Bulk encounter download

The log is a ring of 256 records in flash. Every record has a **sequence number**
that never repeats; `head_seq` is the number of the oldest record still in the
log. Reads do not remove anything: the central removes what it has stored with
LOGACK, so a read lost to a dropped connection is simply read again.

1. (optional) **GETPAGE** → `pending` for progress.
2. **Read `prx_log`**. Each read returns one MTU-bounded batch from the head:

   ```
   [u8 count][u32 first_seq][count x prox_log_entry_t]      // 16 B each
   ```

   `count` fits the negotiated ATT MTU (at most `PRX_LOG_MAX_BATCH = 15` at MTU
   247). `count == 0` → the log is empty, download complete.
3. **Store the batch**, then **LOGACK** `{first_seq, count}`. The tag removes those
   records and the next read returns the next batch. Repeat from 2.

Use plain ATT **Read Requests** (offset 0); a non-zero offset returns an empty
payload. A LOGACK for records already gone is harmless (`removed` 0); one that
starts past `head_seq` is ignored. If the ring overwrote records while the central
was reading, LOGACK removes only the ones still there.

`prox_log_entry_t` (16 B):
```c
uint32 timestampStart;     // tag clock, Unix s: first in-range beacon
uint32 seconds_duration;   // first to last in-range beacon, at least 1
uint8  addr[6];            // peer uid (addr[0] = LSB)
int8   rssi;               // mean RSSI of the in-range beacons [dBm]
int8   tx_power;           // TX power the peer advertised [dBm]
```

### Markers

The log also holds marker records: `addr` = `<type>, FF, FF, FF, FF, FF` (shown
`FF:FF:FF:FF:FF:<type>`), `rssi` = 127, which no real beacon can produce.

| type | name | timestampStart | seconds_duration | tx_power |
|---|---|---|---|---|
| 0x01 | BOOT | clock at boot (restored from flash) | reset cause | boot count (low 7 bits) |
| 0x02 | TIMESET | new clock | clock just before the change | 0 |
| 0x03 | POWEROFF | clock | reason: 1 mode Off, 2 low battery, 3 host SLEEP | 0 |
| 0x04 | START | clock | previous mode | 1 if the clock was set since boot |
| 0xFE | UNREADABLE | 0 | 0 | 0 — served in place of a record the flash could not read, so the download and the sequence go on; acknowledge it like any record |

**Re-dating after a reset.** The clock restarts from the last saved time (saved
hourly and at every clock step) or from the end of the newest logged record,
whichever is later, so records after a BOOT marker are behind by the time the tag
was off but never dated before the ones already logged. When the clock is then set, the TIMESET marker gives the
step (`new − old`): add it to the records between that BOOT and that TIMESET.

## Release trigger

**RELEASE** drives the release-circuit pin **REL (PD01)** HIGH for `width_ms`
milliseconds, then back LOW. REL is driven LOW at boot and is forced LOW before
the tag enters EM4, so the trigger cannot latch on. The command is rejected
(`rcmd = 0x08`, no `0x80`) when `width_ms` is 0 or a previous pulse is still
running. Any BLE central can send it: authentication is still open.

## Firmware update (Silicon Labs AppLoader OTA DFU)

Tags contain the Silicon Labs in-place OTA service and the AppLoader bootloader
stage; an update is a `.gbl` file.

| | UUID |
|---|---|
| Silicon Labs OTA service | `1d14d6ee-fd63-4fa1-bfa4-8f47b42119f0` |
| OTA Control | `f7bf3564-fb6d-4e53-88a4-5e37e0326063` |
| OTA Data (AppLoader only) | `984227f3-34fc-4045-a5d0-2c581f81a153` |

1. On the running tag, write `0x00` to OTA Control. The tag closes the
   connection and restarts in AppLoader mode.
2. Connect again (same address, or address + 1 depending on the AppLoader
   configuration; do not reuse a cached GATT table). Write `0x00` to OTA
   Control, the `.gbl` file in chunks (≤ MTU − 3 bytes) to OTA Data, then `0x03`
   to OTA Control.
3. The tag restarts into the new firmware. Settings and the log are kept.

An interrupted transfer leaves the tag in AppLoader mode: start again at step 2.
Any BLE central can start an update: authentication and signed images are open.

## Changes from 01.02.x (wire-incompatible: major version 02)

- `prx_log` reads carry `u32 first_seq` after the count and **no longer remove
  records**; LOGACK (0x13) removes them. A 01.02.x downloader would read the same
  batch forever.
- GETPAGE returns `head_seq`, `overwritten` and the clock after `pending`.
- New: LOGACK 0x13, GETSTATS 0x14, SETTIME_UNIX 0x15, marker records.
- Beacon: byte 13 (was `master_type`, always 0) = status flags; `count` = records
  in the BLE log.
- Encounters are keyed on the peer's `uid`; register 0x0B = RSSI split (default off).

## Firmware 01.02.x (before 02.00)

Tags in the field may still run 01.02.28 or earlier. Same beacon, service and
control point, but:

- each read of `prx_log` returns **one** 16-byte record and deletes it at once
  (no count, no sequence number, no LOGACK); an empty log answers with ATT error
  0x11. Store each record before the next read.
- no GETPAGE, LOGACK, GETSTATS or SETTIME_UNIX: set the clock with SETTIME
  (`sdate_time_t`); read it with GETTIME. The beacon `count` is the number of
  records waiting; beacon byte 13 is always 0 (no flags).
- The firmware revision string (Device Information, `0x2A26`) tells the
  versions apart.

## Notes
- Negotiate a large MTU (e.g. 247) first for the best throughput (15 records/read).
- Download regularly: when the ring is full the oldest record is overwritten
  (GETPAGE `overwritten` counts them).
- An add-on unit also hands every encounter to its host logger; its BLE log is
  independent of that, so a BLE download of an add-on also returns records the
  host already collected. Markers are only in the BLE log.
