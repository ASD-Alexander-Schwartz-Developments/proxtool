# Third-Party Licenses

proxtool is © 2026 A.S.D - Alexander Schwartz Developments, open source under the
[Apache License 2.0](https://github.com/ASD-Alexander-Schwartz-Developments/proxtool/blob/main/LICENSE).
The ASD name and logo are trademarks of A.S.D and are not covered by the licence.

It uses these open-source components, all under permissive licences:

| Component | Used for | Licence |
|---|---|---|
| Python | runtime | PSF License 2.0 |
| Tkinter, Tcl/Tk | the window | PSF; Tcl/Tk licence (BSD-style) |
| bleak | the computer's Bluetooth | MIT |
| pywinrt (`winrt-*`) | Bluetooth on Windows | MIT |
| dbus-fast | Bluetooth on Linux | MIT |
| typing_extensions | Python compatibility | PSF License 2.0 |
| async-timeout (old Python only) | timeouts | Apache License 2.0 |
| pyBGAPI | the USB NCP adapter | zlib (Silicon Laboratories) |
| pySerial | the adapter's serial port | BSD-3-Clause |
| `sl_bt.xapi` (shipped) | Bluetooth API definition for pyBGAPI | zlib (Silicon Laboratories) |

The full notices are in
[THIRD-PARTY-NOTICES.md](https://github.com/ASD-Alexander-Schwartz-Developments/proxtool/blob/main/proxtool/THIRD-PARTY-NOTICES.md),
which also ships with the ready-made program. The ready-made program is built
with PyInstaller (GPL-2.0 with an exception that allows packaged programs under
any licence).
