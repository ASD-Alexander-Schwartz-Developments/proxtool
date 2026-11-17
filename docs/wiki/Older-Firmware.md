# Older Firmware (01.02.x)

Tags deployed before firmware 02.00 run 01.02.28 or earlier. proxtool reads the
firmware version when it connects and handles these tags too, with what their
firmware offers:

| | Firmware 02.00 and later | Firmware 01.02.x |
|---|---|---|
| Download | the tag deletes a record only after it is saved and confirmed | the tag deletes each record as it sends it; proxtool saves every record before asking for the next, so at most the record in flight can be lost if the link drops |
| Record numbers (`seq`) | yes | no (`-1`) |
| Clock | set in UTC | set in UTC (see below) |
| Settings in the window | yes | no: update the firmware first |
| Counters, details | yes | firmware, clock and registers only |
| Beacon clock flag | yes | no (proxtool judges the clock from the beacon time) |

**Clock: UTC or local time.** The earlier downloader set these tags to the
computer's *local* time, so their records are in local time. proxtool sets UTC,
like for 02.00 tags. If a running study depends on local time, keep it with the
command-line option `--legacy-local-time`, and note which convention each data
set uses.

Updating these tags to the current firmware is recommended: downloads become
loss-free and the clock survives a restart. See [Firmware Updates](Firmware-Updates).
