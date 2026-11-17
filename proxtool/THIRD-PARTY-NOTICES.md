# Third-party software in proxtool

proxtool (© 2026 A.S.D - Alexander Schwartz Developments, Apache License 2.0)
uses the open-source components below. All are under permissive licences: they may be used and
redistributed in open or closed software, provided their copyright and licence
notices are kept, as this file does.

| Component | Used for | Licence | Copyright | Where |
|---|---|---|---|---|
| Python | runtime | PSF License 2.0 | Python Software Foundation | <https://docs.python.org/3/license.html> |
| Tkinter / Tcl/Tk | the window | PSF (Tkinter); Tcl/Tk licence (BSD-style) | PSF; Regents of the University of California, Sun Microsystems and others | <https://www.tcl.tk/software/tcltk/license.html> |
| bleak | Bluetooth LE (all platforms) | MIT | Henrik Blidh and contributors | <https://github.com/hbldh/bleak> |
| pywinrt (`winrt-*` packages) | Bluetooth on Windows | MIT | the pywinrt contributors | <https://github.com/pywinrt/pywinrt> |
| dbus-fast | Bluetooth on Linux (BlueZ over D-Bus) | MIT | Bluetooth Devices authors and contributors | <https://github.com/Bluetooth-Devices/dbus-fast> |
| typing_extensions | Python compatibility | PSF License 2.0 | Python Software Foundation | <https://github.com/python/typing_extensions> |
| async-timeout (Python < 3.11 only) | timeouts | Apache License 2.0 | aio-libs contributors | <https://github.com/aio-libs/async-timeout> |

Not shipped: Pillow (MIT-CMU) was used once to make the icon files in `assets/`.
macOS (pyobjc, MIT) is not supported.

The firmware update speaks the Silicon Labs AppLoader OTA DFU protocol (public
Silicon Labs documentation, AN1086); no Silicon Labs code is part of proxtool.
The ASD name and logo (`assets/`) are trademarks of A.S.D and are not covered
by any open-source licence.

When proxtool is packaged as a stand-alone program (e.g. a Windows .exe made
with PyInstaller), the packaged Python and libraries are redistributed: ship
this file with it. PyInstaller itself is GPL-2.0 with an exception that
explicitly allows packaged programs under any licence.

## MIT licence text (bleak, pywinrt, dbus-fast)

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
the Software, and to permit persons to whom the Software is furnished to do so,
subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

The PSF License 2.0 and the Apache License 2.0 texts are at
<https://docs.python.org/3/license.html> and
<https://www.apache.org/licenses/LICENSE-2.0>.
