# Clock

Every record is dated with the tag's own clock, so set it before deployment and
whenever proxtool shows it in red.

- **Set clock** in the window sets the selected tags to the computer's time, in
  **UTC**. Make sure the computer's own clock is right: Windows "Set time
  automatically", or NTP on Linux.
- The **Clock** column compares the time in each tag's beacon with the computer:
  - `ok`: within 5 s;
  - `off by N s`: set it;
  - `NOT SET`: the tag has no valid time at all.
- After a power cut a tag restarts with the last time it saved, which is behind
  by the time it was off. Its log gets a **BOOT** marker. Setting the clock adds a
  **TIMESET** marker with the size of the step, so the records in between can be
  re-dated afterwards (add the step to every record between that BOOT and that
  TIMESET).
- Automatic collection sets the clock of every tag that is off by more than 5 s.
- A clock step of more than 2 s first closes every open encounter, so no
  encounter mixes the old and the new time.

Tags on firmware 01.02.x are set the same way, in UTC. The earlier downloader set
them to the computer's *local* time; see [Older Firmware](Older-Firmware) if a
running study depends on that.
