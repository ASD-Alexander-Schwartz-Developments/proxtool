# Downloading Data

## In the window

- **Download**: the selected tags, one after the other.
- **Download all**: every tag in range with records waiting.
- The progress bar shows the current tag; the log says how many records each tag
  gave and where they went.

Records are added to `<folder>/<tag id>.csv`, e.g. `C0FFEE001001.csv` for tag
`C0:FF:EE:00:10:01`. Downloading the same tag again adds to the same file.

**Nothing is lost if the download is interrupted.** The tag deletes a record only
after proxtool has written it to the file and confirmed it. If the link drops,
download again to get the rest. A record that was saved but not confirmed comes
twice; it has the same `seq` number both times, so keep one. (Tags on firmware
01.02.x work differently: see [Older Firmware](Older-Firmware).)

A tag keeps the most recent **256** records. When it is full, the oldest is
overwritten, so download regularly. The Mode column shows "log 90 % full" as a
warning.

## The file

One line per record, with a header line:

| Column | Content |
|---|---|
| `seq` | Record number on the tag; it never repeats. `-1` for tags on firmware 01.02.x |
| `start_unix` | Encounter start, seconds since 1970, **UTC** |
| `start_utc` | The same as text, UTC |
| `duration_s` | Duration in seconds, first to last beacon heard (at least 1) |
| `peer` | Id of the other tag |
| `rssi` | Average received signal of the other tag's beacons, dBm |
| `tx_power` | The TX power the other tag announced, dBm |
| `type` | `encounter`, or `marker` for a tag event |
| `detail` | The record in words |

**Markers** record what happened to the tag itself; `peer` is then `FF:FF:FF:FF:FF:0x`:

| Marker | Meaning |
|---|---|
| BOOT | The tag (re)started; `detail` gives the reason (power-on, watchdog, ...). Records after it are behind by the time the tag was off, until the clock is set. |
| TIMESET | The clock was set; `detail` gives the step. |
| START | Logging started (mode changed to logger). |
| POWEROFF | The tag switched off (mode Off, low battery, host request). |
| UNREADABLE | A record the tag's memory could not read; a placeholder so the download goes on. |

How encounters are formed (proximity threshold, silence time, maximum length) is
explained in [Tag Settings](Tag-Settings).

## Coming from the earlier downloader

The earlier NCP scripts wrote everything to one `logs.csv` in **local time**.
proxtool writes one file per tag in **UTC**. The columns map as: Unit = the tag
(the file name), `peer` = the other unit, `rssi` = RSSI, `tx_power` = TX Power,
`start_utc` = Start Time (converted to UTC), `duration_s` = Seconds Duration.
