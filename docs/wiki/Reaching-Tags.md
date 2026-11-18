# Reaching Tags

proxtool reaches tags in one of two ways. Choose it under **Reach tags with** in
the window, or with `--via` on the command line. Everything else works the same
either way: download, clock, settings, firmware update and automatic collection.

| | This computer's Bluetooth (`--via ble`) | USB Bluetooth adapter (`--via ncp`) |
|---|---|---|
| Hardware | the laptop's built-in Bluetooth | a Silicon Labs board running the **Bluetooth NCP** firmware, e.g. a **Thunderboard BG22**, on USB |
| Range | the laptop's antenna | the adapter's; put it next to the tags on a USB extension cable |
| Computers | Windows 10/11; Linux with BlueZ | Windows and Linux, any computer with USB |
| Extra software | none | included in the ready-made program; with Python: `pip install "proxtool[ncp]"` |

## The USB adapter (NCP)

This is how ProxTit tags were downloaded before proxtool (the earlier
`proxtit-downloader-py` scripts, whose code is kept on the repository's
`legacy-pybgapi-downloader` branch). proxtool reads the same adapters.

- **Firmware on the adapter:** the Silicon Labs *Bluetooth - NCP* example for that
  board (from Simplicity Studio), or the image ASD supplied with it. proxtool
  asks the adapter which Bluetooth stack it runs and talks to it accordingly:
  stacks from Simplicity SDK 2024.12 (BGAPI 9) and 2025.12 or later (BGAPI 11)
  are supported. Silicon Labs renumbered parts of the protocol between them.
  If the adapter needs it, flow control is switched automatically.
- **Finding it:** proxtool picks the adapter by its USB id (SEGGER J-Link, as on
  Thunderboards, or a Silicon Labs CP210x). With more than one such device
  plugged in, name the port: in the window it is listed as "USB adapter (NCP) on
  COM7"; on the command line use `--via ncp:COM7` (Windows) or
  `--via ncp:/dev/ttyACM0` (Linux). **Refresh list** looks again after plugging in.
- Silicon Labs development kits (WSTK) show the same USB id. If such a kit runs
  other firmware, proxtool reports "no answer from the NCP adapter" and changes
  nothing on it.

## The computer's Bluetooth

- **Windows:** Bluetooth must be switched on (Settings → Bluetooth & devices).
  Tags do not need to be paired.
- **Linux:** see [Linux Setup](Linux-Setup).
- Range indoors is typically 10–30 m; walls and bodies shorten it.
