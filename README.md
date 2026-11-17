# proxtool

PC tool for ProxTit BLE tags (firmware **02.00.x**): a **window** for users
(find tags, download, set the clock, change settings) and a **command line** for
engineering and the bench test against the peer simulator. It uses the
computer's own Bluetooth LE through [bleak](https://github.com/hbldh/bleak).

| | Windows 10/11 | Linux | macOS |
|---|---|---|---|
| Status | tested (bench, 2026-11-17) | supported, **not yet tested on hardware** | not supported: macOS hides Bluetooth addresses, which proxtool uses to name tags |
| Needs | Python 3.9+ (Tkinter included) | Python 3.9+, `python3-tk`, BlueZ 5.43+ (`bluetoothd` running; user may need to be in the `bluetooth` group) | |

## Two ways to reach the tags

| `--via` | Radio | Install | Notes |
|---|---|---|---|
| `ble` (default) | this computer's Bluetooth | `pip install -e .` | Windows 10/11, Linux (BlueZ) |
| `ncp` or `ncp:PORT` | a USB Bluetooth adapter running the Silicon Labs **NCP** firmware, e.g. a **Thunderboard BG22** | `pip install -e .[ncp]` (adds pyBGAPI) | no Bluetooth needed on the computer; the adapter can sit next to the tags on a USB extension; same on Windows and Linux |

The NCP adapter is how ProxTit tags were downloaded before proxtool (the earlier
`proxtit-downloader-py` scripts). proxtool replaces those scripts and reads the
same adapters; it finds the adapter by its USB id (SEGGER J-Link or Silicon Labs
CP210x) or takes the port (`--via ncp:COM7`, `--via ncp:/dev/ttyACM0`). In the
window, choose the radio under "Reach tags with". Whatever the radio, proxtool
does the same things: download, clock, settings, firmware update, gateway.

The adapter needs the Silicon Labs "Bluetooth - NCP" firmware for its board
(Simplicity Studio example, or the image ASD supplied). proxtool talks BGAPI with
the bundled API definition (Simplicity SDK 2024.12); a newer or older stack is
reported and normally works, since only scanning, connections and GATT are used.

**Unattended collection (gateway)** — what the earlier downloader did: keep
scanning, and every tag that comes in range with records waiting or a wrong
clock gets its clock set and its log downloaded:

```sh
proxtool --via ncp gateway -o ProxTitData      # Ctrl-C stops
```

In the window the same is "Download and set the clock of tags in range
automatically". Each tag is visited at most once a minute (`--revisit`).

**Tags still on firmware 01.02.x** (field units from before 02.00) are read
too: proxtool detects the version and uses that firmware's download (each read
returns one record and deletes it, so proxtool stores every record before the
next read). Their settings are not changed from the window; update the firmware
first. Their clock is set in **UTC**, like 02.00 tags. The earlier downloader set
the computer's *local* time: add `--legacy-local-time` to keep that convention
for an ongoing study, and note which one each data set uses.

**Coming from the earlier downloader's `logs.csv`:** proxtool writes one file
per tag, `<tag address>.csv`, with times in UTC (`start_unix` and
`start_utc`). Columns map as: Unit = the tag (file name), `peer` = the other
tag, `rssi`, `tx_power`, `start_utc` = Start Time, `duration_s` = Seconds
Duration. Records from 01.02.x tags have `seq` -1.

```sh
pip install -e Host/proxtool          # pulls bleak; gives `proxtool` and `proxtool-gui`
pip install -e "Host/proxtool[ncp]"   # also the USB NCP adapter (pyBGAPI)
proxtool-gui                          # the window   (or: python -m proxtool.gui)
proxtool -h                           # the command line (or: python -m proxtool)
```

## The window

- **Tag list**: every ProxTit tag heard in the last 2 minutes, with its mode,
  records waiting, battery, clock (**NOT SET** or **off by N s** in red), signal
  and when it was last heard. The bench simulator and its virtual peers are not
  listed.
- **Download** (selected tags) / **Download all** (every tag with records waiting):
  appends to `<folder>/<address>.csv` (same file and format as `proxtool download`).
  Each batch is on disk before the tag is told to delete it; a broken link loses
  nothing, the rest stays on the tag for the next try.
- **Set clock**: sets the selected tags to this computer's time (UTC). Tags log in
  UTC; a tag that lost power shows NOT SET until it is set.
- **Settings...**: the encounter settings (mode, proximity threshold, silence time,
  maximum length, TX power) with their units, limits and what they do; "Show radio
  schedule settings" adds beacon and scan timing. With several tags selected, the
  values of the first are shown and Save writes them to all, so a study's tags get
  identical settings. Only changed values are written; the log shows what each tag
  accepted (the tag may round, e.g. TX power to a step its radio supports).
- **Details...**: firmware, clock offset, log state, every setting and the tag's
  counters.
- **Update firmware...**: pick a `.gbl` file; the window shows the version it
  contains and asks before starting. See "Firmware update" below.
- **About**: version, copyright, licence, third-party notices.
- The download folder is remembered in `~/.proxtool.json`.

All Bluetooth work runs in one background thread, one tag at a time; scanning
pauses during a connection.

## Firmware update

The tag firmware contains the Silicon Labs in-place OTA DFU service and the
AppLoader bootloader stage, so a tag is updated over Bluetooth from the `.gbl`
file the firmware build produces (`Proxtit.gbl`):

```sh
proxtool update C0:FF:EE:12:34:56 proxtit-02.00.01.gbl --yes
```

1. proxtool writes 0x00 to OTA Control on the running tag; it restarts in
   AppLoader (update) mode.
2. proxtool connects to the AppLoader (same address, or address + 1), sends the
   file in chunks of up to 244 bytes (each acknowledged), then 0x03.
3. The tag restarts into the new firmware; proxtool reads the firmware version
   back. Settings and stored records (NVM3) are kept.

An interrupted update leaves the tag in AppLoader mode (it is not listed as a
ProxTit tag then): run the update again. proxtool never reuses Windows' cached
GATT table, because the AppLoader exposes a different one at the same address.

**Security (open):** any Bluetooth central in range can start an update; the
bootloader accepts unsigned images. Before field release decide on signed
`.gbl` files (bootloader `BOOTLOADER_ENFORCE_SIGNED_UPGRADE`, a signing key kept
by ASD) and on authentication for the control commands.

## Licence

© 2026 A.S.D - Alexander Schwartz Developments. proxtool is open source under the
[Apache License 2.0](LICENSE) (see also [NOTICE](NOTICE)). The ASD name and logo
are trademarks of A.S.D and are not licensed (Apache-2.0 section 6).
Third-party components and their licences (all permissive: PSF, MIT,
Apache-2.0): [proxtool/THIRD-PARTY-NOTICES.md](proxtool/THIRD-PARTY-NOTICES.md).

What is open and what is not:

| Part | Status |
|---|---|
| proxtool (this folder): window, command line, bench checker | open, Apache-2.0 |
| ProxTit BLE protocol (beacon, GATT, download, firmware update) | open: [docs/ble-protocol.md](docs/ble-protocol.md) |
| ProxTit firmware, peer simulator firmware | closed (ASD) |
| RoostBox link (future) | closed: a separate plugin package, see below |

## Extending: RoostBox and other links (plan)

RoostBox, a future ASD communicator, will collect tag data instead of the
laptop's Bluetooth. Its protocol stays closed, so it will not live in this
repository. The plan:

- proxtool gets a small **transport interface**: "list tags", "download a tag",
  "set clock / settings", "update firmware". The built-in transport is the
  laptop's Bluetooth (today's `ble.py` / `dfu.py`).
- The RoostBox transport is a **separate, closed package** (e.g.
  `proxtool-roostbox`, distributed as a wheel to customers). It registers itself
  under the Python entry-point group `proxtool.transports`; proxtool loads
  whatever transports are installed and shows them as a choice in the window.
- Apache-2.0 allows this: the closed plugin may use and extend proxtool without
  being opened. Only proxtool's own notices must be kept.
- **Keeping a protocol closed is not security.** Python code in a distributed
  wheel can be read (and compiled modules reverse-engineered). Protect RoostBox
  with authentication and encryption (per-device or per-study keys); the closed
  source only keeps the details private.
- The interface exists: `proxtool/link.py` (Transport, Link). The NCP adapter
  (`ncp.py`), RoostBox's predecessor, is the second built-in transport and shows
  what a RoostBox plugin implements: scan for beacons, connect, read and write
  GATT characteristics. If RoostBox works at a higher level (it downloads the
  tags itself and the PC fetches files from it), the interface gains a
  "collected records" call then.

Contributions from outside ASD, if accepted, come in under Apache-2.0 (section
5). Add a contributor licence agreement (CLA) first if ASD may later want to
re-license proxtool or move code from it into closed products.

## Command line

| Command | Does |
|---|---|
| `proxtool scan` | List tags (mode, battery, records waiting, clock, flags) and simulators in range |
| `proxtool monitor [ADDR]` | Print every beacon as it arrives |
| `proxtool info ADDR` | Firmware, clock vs this PC, config, log state, GETSTATS counters |
| `proxtool settime ADDR` | Set the tag clock from this PC (UTC) |
| `proxtool getcfg ADDR` / `setcfg ADDR REG VALUE` | Config registers, by name (`silence_gap_s`) or number (`0x0A`) |
| `proxtool download ADDR [-o DIR]` | Download the log to `DIR/<address>.csv`; each batch is written to disk before it is acknowledged, so a broken link loses nothing |
| `proxtool gateway [-o DIR]` | Keep collecting: download and clock every tag that comes in range (see "Two ways to reach the tags") |
| `proxtool update ADDR FILE.gbl --yes` | Firmware update over Bluetooth (see "Firmware update") |
| `proxtool --via ncp[:PORT] ...` | Any command through a USB NCP adapter instead of this computer's Bluetooth |
| `proxtool release ADDR MS --yes` | Pulse the drop-off output |
| `proxtool bench start ADDR... [--clear]` | Find the simulator, write the bench config and clock to the tags, save `bench_session.json` |
| `proxtool bench check [--every S]` | Download the tags and compare with the simulator scenario: PASS / FAIL with the missing and unexpected encounters, start/end error statistics, simulator and tag restarts. `--every 3600` repeats it hourly for overnight runs |
| `proxtool pair-check A.csv ADDR_A B.csv ADDR_B` | Two real tags: did each log the other at the same times |

CSV columns: `seq, start_unix, start_utc, duration_s, peer, rssi, tx_power, type,
detail`. `type` is `marker` for BOOT / TIMESET / POWEROFF / START records (see
[docs/ble-protocol.md](docs/ble-protocol.md)). A record downloaded twice (an ack
that never reached the tag) has the same `seq`; readers keep one.

The `bench` commands need ASD's peer simulator, a development board running
closed ASD firmware that plays a fixed scenario of virtual tags; they are used
for ASD's firmware testing.

## Tests

```sh
python -m unittest discover -s tests
```

No radio needed: they cover the wire format, settings, firmware-update file
checks, the bench verifier, and the NCP transport and 01.02.x download against
a stand-in adapter (`tests/test_ncp.py`). Two tests compare against the closed firmware
sources and are skipped when those are not next to proxtool.
