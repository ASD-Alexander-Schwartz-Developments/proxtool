# Firmware Updates

Tags are updated over Bluetooth, through either radio, from a `.gbl` firmware
file supplied by ASD.

1. **Download the tag first.** The update keeps the settings and the stored
   records, but download them anyway in case something goes wrong.
2. Select **one** tag and press **Update firmware...**, then choose the `.gbl` file.
   proxtool checks the file and shows the version it contains; confirm.
3. Keep the tag within a few metres until the update has finished, about 1–2
   minutes. The tag restarts in update mode, receives the file, then restarts
   with the new firmware. proxtool reads the new version back and logs it.

If the update is interrupted, the tag stays in update mode and no longer appears
as a ProxTit tag: run the update again with the same file.

Command line: `proxtool update C0:FF:EE:00:10:01 proxtit-02.00.01.gbl --yes`.

Tags on firmware 01.02.28 contain the same update service and are updated the
same way. If a tag's firmware has none, proxtool says so and changes nothing.

**Updating from firmware 01.x.** At its first start the new firmware checks the
settings it finds. Settings that are out of range go back to their defaults. If
the radio schedule (beacon and scan timing) still has the old factory values, it
moves to the current defaults, which save battery and hear neighbours better.
Settings someone changed for a study are kept. The log gets a **SETTINGS** marker
with the number of settings changed. After updating, open **Settings...** and
check them, and use the same settings on all tags of a study.
