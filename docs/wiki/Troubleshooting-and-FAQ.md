# Troubleshooting and FAQ

**No tags appear.**
- Is Bluetooth on (or the USB adapter plugged in and chosen under *Reach tags with*)?
- Tags in **Off** mode do not advertise: wake them with the magnet.
- Range is shorter through walls, bodies and metal. Move closer.
- With the computer's Bluetooth on Windows, the first scan after a while
  sometimes hears nothing; wait a few seconds.

**"Could not connect" / timeout.** The tag moved out of range, or another program
or computer is connected to it (a tag accepts one connection at a time). Try again
closer.

**A download stopped half-way.** Nothing is lost on firmware 02.00 and later:
download again. Records already saved but not confirmed come a second time with
the same `seq`; keep one.

**The clock column is red.** Press **Set clock**. After a power cut this is
expected; see [Clock](Clock).

**Many short encounters where I expected one.** Probably false splits: see
"Choosing the silence time" in [Tag Settings](Tag-Settings).

**"no answer from the NCP adapter".** The chosen USB device is not running the
Silicon Labs NCP firmware, or another program has its port open. See
[Reaching Tags](Reaching-Tags).

**"several possible adapters".** Name one: `--via ncp:COM7`, or choose it in the
window.

**After a firmware update the tag is gone.** It may be waiting in update mode:
run the update again ([Firmware Updates](Firmware-Updates)).

**Why UTC?** So that data from different computers, time zones and summer time
line up. Convert to local time in the analysis.

**Is the battery percentage right?** Not yet: the reading is not calibrated. Use
it as a trend only.

**Who can change my tags?** Today, any Bluetooth device in range can change
settings or start an update; authentication is planned. Keep this in mind in
public places.
