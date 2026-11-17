# Automatic Collection

A computer can collect by itself, for example next to a roost or a feeding
station: every tag that comes in range with records waiting, or with a wrong
clock, gets its clock set and its log downloaded. This is what the earlier NCP
downloader did.

- **In the window:** tick **Download and set the clock of tags in range
  automatically**. Keep the window open.
- **Command line:** `proxtool --via ncp gateway -o D:\Study-2026\ProxTit`
  (Ctrl-C stops). Each visit is printed with the time, the tag, its firmware and
  the number of records.

Each tag is visited at most once a minute (`--revisit 60`), so a tag sitting next
to the computer is not kept busy: every connection costs the tag battery.

For a long unattended run:

- Use the **USB adapter** on an extension cable placed where the tags pass (see
  [Reaching Tags](Reaching-Tags)).
- Stop the computer from sleeping (Windows: Settings → System → Power → Sleep:
  Never when plugged in). A sleeping computer also cuts the power of the USB adapter.
- Put the download folder on a disk with room. Files only grow.
- Check the log or the console now and then for red lines or errors.
